import unittest

from fastapi import FastAPI, HTTPException

from app.errors import register_exception_handlers


class ErrorsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.app = FastAPI()
        register_exception_handlers(self.app)

    def test_http_error_returns_status_and_plain_text(self) -> None:
        handler = self.app.exception_handlers[HTTPException]
        response = handler(
            None,
            HTTPException(
                status_code=400,
                detail="Bad SQL",
            ),
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.body, b"Bad SQL")

    def test_unhandled_error_does_not_leak_exception_text(self) -> None:
        handler = self.app.exception_handlers[Exception]
        response = handler(None, RuntimeError("secret internal detail"))

        self.assertEqual(response.status_code, 500)
        self.assertNotIn(b"secret internal detail", response.body)


if __name__ == "__main__":
    unittest.main()
