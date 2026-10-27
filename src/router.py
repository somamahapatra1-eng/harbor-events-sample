"""Harbor Events router.

Original sample. One Lambda accepts two already-authenticated callers:

- JWT: API Gateway validated a Cognito ID token. The username is cognito:username.
- SigV4: API Gateway authenticated an IAM caller. The identity is the assumed-role ARN.

Queue URLs come from AppConfig. The fallback map below is only for local tests.
"""

import json
import os

DEFAULT_ROUTES = {
    "acme": {
        "region": "us-east-1",
        "queue_url": "https://sqs.us-east-1.amazonaws.com/123456789012/harbor-acme-use1",
    },
    "globex": {
        "region": "eu-west-1",
        "queue_url": "https://sqs.eu-west-1.amazonaws.com/123456789012/harbor-globex-euw1",
    },
}


def identify_caller(event):
    request_context = event.get("requestContext") or {}
    authorizer = request_context.get("authorizer") or {}
    claims = authorizer.get("claims") or authorizer
    username = claims.get("cognito:username")
    if username:
        return {"method": "jwt", "caller": username}

    user_arn = (request_context.get("identity") or {}).get("userArn")
    if user_arn:
        return {"method": "sigv4", "caller": user_arn}

    raise PermissionError("caller identity is missing")


def select_route(routes, tenant_id):
    route = routes.get(tenant_id)
    if not route or "queue_url" not in route or "region" not in route:
        raise KeyError(tenant_id)
    return route


def load_routes(appconfig_client=None):
    application = os.environ.get("APPCONFIG_APPLICATION")
    environment = os.environ.get("APPCONFIG_ENVIRONMENT")
    profile = os.environ.get("APPCONFIG_PROFILE")
    if not (appconfig_client and application and environment and profile):
        return DEFAULT_ROUTES

    session = appconfig_client.start_configuration_session(
        ApplicationIdentifier=application,
        EnvironmentIdentifier=environment,
        ConfigurationProfileIdentifier=profile,
    )
    latest = appconfig_client.get_latest_configuration(
        ConfigurationToken=session["InitialConfigurationToken"]
    )
    raw = latest["Configuration"].read()
    if not raw:
        return DEFAULT_ROUTES
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def send_to_queue(route, message, sqs_client_factory=None):
    if sqs_client_factory is None:
        import boto3

        sqs_client_factory = lambda region: boto3.client("sqs", region_name=region)
    client = sqs_client_factory(route["region"])
    return client.send_message(
        QueueUrl=route["queue_url"],
        MessageBody=json.dumps(message),
    )


def presigned_get_url(bucket, key, s3_client=None, expires_in=900):
    if s3_client is None:
        import boto3

        s3_client = boto3.client("s3")
    return s3_client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expires_in,
    )


def handler(event, context, appconfig_client=None, sqs_client_factory=None, s3_client=None):
    try:
        caller = identify_caller(event)
    except PermissionError as exc:
        return _response(401, {"error": str(exc)})

    raw_body = event.get("body") or {}
    if isinstance(raw_body, str):
        try:
            body = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError:
            return _response(400, {"error": "body must be JSON"})
    else:
        body = raw_body

    tenant_id = body.get("tenantId")
    if not tenant_id:
        return _response(400, {"error": "tenantId is required"})

    try:
        route = select_route(load_routes(appconfig_client), tenant_id)
    except KeyError:
        return _response(404, {"error": "unknown tenant"})

    message = {
        "tenantId": tenant_id,
        "caller": caller["caller"],
        "authMethod": caller["method"],
        "payload": body.get("payload", {}),
    }
    send_to_queue(route, message, sqs_client_factory=sqs_client_factory)

    result = {
        "accepted": True,
        "tenantId": tenant_id,
        "authMethod": caller["method"],
        "queueRegion": route["region"],
    }
    object_key = body.get("objectKey")
    bucket = os.environ.get("BUCKET_NAME")
    if object_key and bucket:
        result["presignedUrl"] = presigned_get_url(
            bucket, object_key, s3_client=s3_client
        )
    return _response(202, result)


def _response(status, payload):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload),
    }
