import json
import os
import unittest

from router import handler, identify_caller, select_route


SIGV4_EVENT = {
    "requestContext": {
        "identity": {
            "userArn": "arn:aws:sts::123456789012:assumed-role/harbor-tenant-acme/external"
        }
    },
    "body": json.dumps({"tenantId": "acme", "payload": {"n": 1}}),
}

JWT_EVENT = {
    "requestContext": {
        "authorizer": {"claims": {"cognito:username": "ada@example.com"}}
    },
    "body": json.dumps(
        {"tenantId": "globex", "objectKey": "globex/report.txt", "payload": {}}
    ),
}


class FakeSqs:
    def __init__(self):
        self.sent = []

    def send_message(self, QueueUrl, MessageBody):
        self.sent.append({"QueueUrl": QueueUrl, "MessageBody": MessageBody})
        return {"MessageId": "msg-1"}


class FakeS3:
    def generate_presigned_url(self, operation, Params, ExpiresIn):
        return "https://example.com/{}/{}?expires={}".format(
            Params["Bucket"], Params["Key"], ExpiresIn
        )


class RouterTests(unittest.TestCase):
    def test_jwt_caller_is_the_cognito_username(self):
        caller = identify_caller(JWT_EVENT)
        self.assertEqual(caller["method"], "jwt")
        self.assertEqual(caller["caller"], "ada@example.com")

    def test_sigv4_caller_is_the_assumed_role_arn(self):
        caller = identify_caller(SIGV4_EVENT)
        self.assertEqual(caller["method"], "sigv4")
        self.assertIn("assumed-role/harbor-tenant-acme", caller["caller"])

    def test_missing_caller_is_rejected(self):
        with self.assertRaises(PermissionError):
            identify_caller({"requestContext": {}})

    def test_unknown_tenant_has_no_route(self):
        with self.assertRaises(KeyError):
            select_route(
                {"acme": {"region": "us-east-1", "queue_url": "https://example"}},
                "other",
            )

    def test_sigv4_event_is_sent_to_the_mapped_queue(self):
        sqs = FakeSqs()
        response = handler(SIGV4_EVENT, None, sqs_client_factory=lambda region: sqs)
        self.assertEqual(response["statusCode"], 202)
        body = json.loads(response["body"])
        self.assertEqual(body["authMethod"], "sigv4")
        self.assertEqual(body["queueRegion"], "us-east-1")
        self.assertEqual(len(sqs.sent), 1)
        self.assertIn("us-east-1", sqs.sent[0]["QueueUrl"])

    def test_jwt_event_can_return_a_presigned_url(self):
        os.environ["BUCKET_NAME"] = "harbor-files-example"
        try:
            response = handler(
                JWT_EVENT,
                None,
                sqs_client_factory=lambda region: FakeSqs(),
                s3_client=FakeS3(),
            )
        finally:
            os.environ.pop("BUCKET_NAME", None)
        body = json.loads(response["body"])
        self.assertEqual(response["statusCode"], 202)
        self.assertEqual(body["authMethod"], "jwt")
        self.assertIn("globex/report.txt", body["presignedUrl"])


if __name__ == "__main__":
    unittest.main()
