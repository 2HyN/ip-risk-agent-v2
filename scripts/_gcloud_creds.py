"""gcloud CLI 자격증명으로 Vertex 를 쓰는 우회.

ADC(application-default) 토큰이 만료돼 재인증(브라우저)이 필요할 때,
살아 있는 CLI 자격증명(`gcloud auth print-access-token`)으로 액세스 토큰을
발급하는 Credentials. 평가 스크립트들이 `GCLOUD_CLI_CREDS=1` 일 때
vertex_config 에 주입한다. 토큰은 ~1시간이므로 만료 10분 전 재발급.
"""

from __future__ import annotations

import datetime
import shutil
import subprocess

import google.auth.credentials


class GcloudCliCredentials(google.auth.credentials.Credentials):
    def refresh(self, request) -> None:  # noqa: ARG002 - 인터페이스 규약
        gcloud = shutil.which("gcloud") or "gcloud"
        token = subprocess.run(
            [gcloud, "auth", "print-access-token"],
            capture_output=True, text=True, check=True, timeout=30,
        ).stdout.strip()
        self.token = token
        self.expiry = datetime.datetime.utcnow() + datetime.timedelta(minutes=50)


def maybe_inject(vertex_config: dict) -> dict:
    import os

    if os.environ.get("GCLOUD_CLI_CREDS"):
        vertex_config = dict(vertex_config)
        vertex_config["credentials"] = GcloudCliCredentials()
    return vertex_config
