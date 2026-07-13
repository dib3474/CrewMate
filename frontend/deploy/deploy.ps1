# CrewMate 프론트엔드 배포 스크립트 (Windows PowerShell)
# 사용법: powershell -ExecutionPolicy Bypass -File deploy/deploy.ps1

$ErrorActionPreference = "Stop"

$BUCKET = "crewmate-frontend-465105354705"
$DISTRIBUTION_ID = "E3C8JMPJGD7Z3Q"

Write-Host "[1/3] 프로덕션 빌드..." -ForegroundColor Cyan
npm run build

Write-Host "[2/3] S3 업로드 (기존 파일 정리 포함)..." -ForegroundColor Cyan
# 해시된 정적 에셋 먼저 업로드 (장기 캐시)
aws s3 sync dist/assets/ "s3://$BUCKET/assets/" --delete --cache-control "public,max-age=31536000,immutable"
# 나머지 파일 동기화 (index.html 제외)
aws s3 sync dist/ "s3://$BUCKET" --delete --exclude "index.html" --exclude "assets/*"
# index.html은 항상 최신, 캐시 안 함
aws s3 cp dist/index.html "s3://$BUCKET/index.html" --cache-control "no-cache,no-store,must-revalidate" --content-type "text/html"

Write-Host "[3/3] CloudFront 캐시 무효화..." -ForegroundColor Cyan
aws cloudfront create-invalidation --distribution-id $DISTRIBUTION_ID --paths "/*" | Out-Null

Write-Host "배포 완료! https://d1872k8ivu18th.cloudfront.net" -ForegroundColor Green
