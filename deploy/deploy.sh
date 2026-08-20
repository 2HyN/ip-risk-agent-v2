#!/usr/bin/env bash
# IP Risk Agent 배포 — 이미지를 만들고 Cloud Run 두 서비스를 갱신한다.
#
# 이 스크립트는 **이미 존재하는 자원을 갱신**한다. 프로젝트·Firestore·큐·버킷·
# 서비스 계정 생성은 콘솔 작업이며 deploy/CONSOLE_TASKS.md 에 정리했다.
#
# 사용:
#   export PROJECT_ID=aj28-1 REGION=asia-northeast3
#   ./deploy/deploy.sh
#
# 빌드 방식은 자동으로 정해진다.
#   - 로컬 docker 가 있으면 로컬 빌드
#   - 없으면 Cloud Build (GCP 에서 빌드)
#   - BUILD_WITH=cloudbuild|docker 로 강제할 수 있다
#
# 환경변수와 secret 은 이 스크립트가 건드리지 않는다. Cloud Run 서비스에
# 이미 설정되어 있어야 하며, 목록은 cloudrun/*.env.example 을 참고한다.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?PROJECT_ID is required}"
REGION="${REGION:-asia-northeast3}"
REPO="${ARTIFACT_REPO:-ip-risk-agent}"
TAG="${TAG:-$(git rev-parse --short HEAD 2>/dev/null || echo latest)}"

API_SERVICE="${API_SERVICE:-ip-risk-agent-api}"
WORKER_SERVICE="${WORKER_SERVICE:-ip-risk-agent-worker}"
API_SA="${API_SA:-app-api-sa@${PROJECT_ID}.iam.gserviceaccount.com}"
WORKER_SA="${WORKER_SA:-analysis-worker-sa@${PROJECT_ID}.iam.gserviceaccount.com}"

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/ip-risk-agent:${TAG}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

# ---------------------------------------------------------------- 빌드 방식

if [[ -z "${BUILD_WITH:-}" ]]; then
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    BUILD_WITH=docker
  else
    BUILD_WITH=cloudbuild
  fi
fi

echo "==> 프로젝트 ${PROJECT_ID} / 리전 ${REGION}"
echo "==> 이미지  ${IMAGE}"
echo "==> 빌드    ${BUILD_WITH}"
echo

echo "==> 인덱스 파일이 코드와 일치하는지 확인"
python scripts/generate_firestore_indexes.py --check

case "${BUILD_WITH}" in
  docker)
    echo "==> 로컬 빌드"
    docker build -f deploy/Dockerfile -t "${IMAGE}" .
    echo "==> 푸시"
    docker push "${IMAGE}"
    ;;
  cloudbuild)
    # 컨텍스트를 통째로 업로드하므로 루트 .dockerignore 가 반드시 있어야 한다.
    # 없으면 .venv 와 node_modules 수 GB 를 매번 올리게 된다.
    if [[ ! -f .dockerignore ]]; then
      echo "오류: 저장소 루트에 .dockerignore 가 없다. 업로드가 매우 커진다." >&2
      exit 1
    fi
    echo "==> Cloud Build"
    gcloud builds submit \
      --project="${PROJECT_ID}" \
      --config=deploy/cloudbuild.yaml \
      --substitutions="_IMAGE=${IMAGE}" \
      .
    ;;
  *)
    echo "오류: BUILD_WITH 는 docker 또는 cloudbuild 여야 한다 (받은 값: ${BUILD_WITH})" >&2
    exit 1
    ;;
esac

# ---------------------------------------------------------------- 배포
# API 와 워커는 같은 이미지를 쓰고 진입점만 다르다. 두 서비스가 항상 같은
# 코드로 도는 것이 중요하다 — 버전이 갈리면 계약 불일치를 디버깅하기 어렵다.

echo
echo "==> API 배포: ${API_SERVICE}"
gcloud run deploy "${API_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --service-account="${API_SA}" \
  --command="sh" \
  --args="-c,uvicorn ip_risk_agent.main:app --host 0.0.0.0 --port \$PORT" \
  --allow-unauthenticated \
  --quiet

echo "==> 워커 배포: ${WORKER_SERVICE}"
# 워커는 공개하지 않는다. Cloud Tasks 서비스 계정만 호출할 수 있어야 한다.
gcloud run deploy "${WORKER_SERVICE}" \
  --project="${PROJECT_ID}" \
  --region="${REGION}" \
  --image="${IMAGE}" \
  --service-account="${WORKER_SA}" \
  --command="sh" \
  --args="-c,uvicorn ip_risk_agent.worker:app --host 0.0.0.0 --port \$PORT" \
  --no-allow-unauthenticated \
  --quiet

API_URL="$(gcloud run services describe "${API_SERVICE}" \
  --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')"
WORKER_URL="$(gcloud run services describe "${WORKER_SERVICE}" \
  --project="${PROJECT_ID}" --region="${REGION}" --format='value(status.url)')"

echo
echo "==> 배포 완료"
echo "    API    : ${API_URL}"
echo "    WORKER : ${WORKER_URL}"
echo
echo "==> 연결 상태"
curl -fsS "${API_URL}/health" || {
  echo "health 확인 실패" >&2
  exit 1
}
echo
echo
echo "sources.skipped 가 비어 있지 않으면 아직 붙지 않은 provider 가 있다는 뜻이다."
echo "무엇이 왜 빠졌는지는 위 응답에 그대로 적혀 있다."
