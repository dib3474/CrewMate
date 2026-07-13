# CrewMate 프론트엔드 배포 스크립트 (Windows PowerShell)
# 사용법: npm run deploy  (또는) powershell -ExecutionPolicy Bypass -File deploy/deploy.ps1

# 주의: ErrorActionPreference를 Stop으로 두면 aws CLI가 stderr에 찍는 진행률 때문에
# 스크립트가 중간에 멈출 수 있어 Continue로 둔다.
$ErrorActionPreference = "Continue"

$BUCKET = "crewmate-frontend-465105354705"
$DISTRIBUTION_ID = "E3C8JMPJGD7Z3Q"

Write-Host "[1/4] 프로덕션 빌드..." -ForegroundColor Cyan
npm run build
if ($LASTEXITCODE -ne 0) { Write-Host "빌드 실패. 중단." -ForegroundColor Red; exit 1 }

Write-Host "[2/4] S3 전체 동기화 (에셋 + 삭제)..." -ForegroundColor Cyan
# 단일 sync로 모든 파일 업로드 + 오래된 파일 삭제 (가장 안정적)
aws s3 sync dist/ "s3://$BUCKET" --delete

Write-Host "[3/4] index.html 강제 최신화 (캐시 방지 헤더)..." -ForegroundColor Cyan
# index.html은 항상 최신 참조를 위해 no-cache로 덮어씀
aws s3 cp dist/index.html "s3://$BUCKET/index.html" --cache-control "no-cache,no-store,must-revalidate" --content-type "text/html"

# 업로드된 index.html이 최신 JS를 참조하는지 검증
Write-Host "  -> S3 index.html 참조 확인:" -ForegroundColor DarkGray
aws s3 cp "s3://$BUCKET/index.html" - | Select-String "assets/index-"

Write-Host "[4/4] CloudFront 캐시 무효화..." -ForegroundColor Cyan
aws cloudfront create-invalidation --distribution-id $DISTRIBUTION_ID --paths "/*" --query "Invalidation.Status" --output text

Write-Host "배포 완료! https://d1872k8ivu18th.cloudfront.net" -ForegroundColor Green
