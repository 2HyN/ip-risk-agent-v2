#!/usr/bin/env bash
# 코드의 REQUIRED_COMPOSITE_INDEXES 에서 생성됨. 손으로 고치지 않는다.
# 다시 만들려면: python scripts/generate_firestore_indexes.py
#
# 이미 존재하는 인덱스는 ALREADY_EXISTS 로 실패한다. 정상이며 무시해도 된다.
# 그래서 하나가 실패해도 나머지를 계속 시도하도록 set -e 를 쓰지 않는다.
set -uo pipefail

DATABASE="${FIRESTORE_DATABASE:-(default)}"

gcloud firestore indexes composite create \
    --database="$DATABASE" \
    --collection-group=memberships \
    --field-config=field-path=record_kind,order=ascending \
    --field-config=field-path=risk_workspace_id,order=ascending

gcloud firestore indexes composite create \
    --database="$DATABASE" \
    --collection-group=memberships \
    --field-config=field-path=record_kind,order=ascending \
    --field-config=field-path=user_id,order=ascending \
    --field-config=field-path=status,order=ascending

gcloud firestore indexes composite create \
    --database="$DATABASE" \
    --collection-group=memberships \
    --field-config=field-path=record_kind,order=ascending \
    --field-config=field-path=email,order=ascending

gcloud firestore indexes composite create \
    --database="$DATABASE" \
    --collection-group=workspace_mounts \
    --field-config=field-path=record_kind,order=ascending \
    --field-config=field-path=risk_workspace_id,order=ascending

gcloud firestore indexes composite create \
    --database="$DATABASE" \
    --collection-group=workspace_mounts \
    --field-config=field-path=record_kind,order=ascending \
    --field-config=field-path=risk_workspace_id,order=ascending \
    --field-config=field-path=mounted_by_user_id,order=ascending

gcloud firestore indexes composite create \
    --database="$DATABASE" \
    --collection-group=risks \
    --field-config=field-path=record_kind,order=ascending \
    --field-config=field-path=artifact_id,order=ascending \
    --field-config=field-path=analysis_type,order=ascending \
    --field-config=field-path=lifecycle_state,order=ascending

gcloud firestore indexes composite create \
    --database="$DATABASE" \
    --collection-group=risks \
    --field-config=field-path=record_kind,order=ascending \
    --field-config=field-path=risk_workspace_id,order=ascending

echo "요청한 복합 인덱스 7개."
echo "생성 상태 확인:"
echo "  gcloud firestore indexes composite list --format='table(name.basename(),state)'"
