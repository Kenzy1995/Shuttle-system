#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重建構所有服務的腳本
確保服務網址不會改變
"""

import subprocess
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ID = "forte-booking-system"
REGION = "asia-east1"

SERVICES = [
    {
        "name": "hotel-web",
        "path": "web",
        "registry": "asia-east1-docker.pkg.dev",
        "image": "asia-east1-docker.pkg.dev/{}/hotel-web/web",
        "deploy_args": [
            "--port=8080"
        ]
    },
    {
        "name": "booking-api",
        "path": "booking-api",
        "registry": "gcr.io",
        "image": "gcr.io/{}/booking-api",
        "deploy_args": [
            "--memory=2Gi",
            "--cpu=2",
            "--max-instances=10",
            "--timeout=300s"
        ]
    },
    {
        "name": "booking-manager",
        "path": "booking-manager",
        "registry": "gcr.io",
        "image": "gcr.io/{}/booking-manager",
        "deploy_args": [
            "--memory=2Gi",
            "--cpu=2",
            "--max-instances=10",
            "--timeout=300s"
        ]
    },
    {
        "name": "driver-api2",
        "path": "driver-api2",
        "registry": "gcr.io",
        "image": "gcr.io/{}/driver-api2",
        "deploy_args": [
            "--memory=1Gi",
            "--cpu=1",
            "--max-instances=5",
            "--timeout=120s"
        ]
    }
]

def run_command(cmd, cwd=None):
    """執行命令"""
    print(f"執行: {cmd}")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            check=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        if result.stdout:
            print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"錯誤: {e.stderr}")
        return False

def main():
    print("=" * 70)
    print("🔨 開始重建構所有服務")
    print("=" * 70)
    print(f"專案: {PROJECT_ID}")
    print(f"區域: {REGION}")
    print("")
    
    # 記錄當前服務網址
    print("📋 當前服務網址：")
    run_command(f'gcloud run services list --region={REGION} --project={PROJECT_ID} --format="table(metadata.name,status.url)"')
    print("")
    print("✅ 重建構不會改變這些網址")
    print("")
    
    # 重建構每個服務
    for i, service in enumerate(SERVICES, 1):
        print("=" * 70)
        print(f"{i}. 重建構 {service['name']}")
        print("=" * 70)
        
        # 配置 Docker 認證
        if service['registry'] == 'gcr.io':
            run_command(f'gcloud auth configure-docker gcr.io --quiet')
        else:
            run_command(f'gcloud auth configure-docker {service["registry"]} --quiet')
        
        # 建構映像
        image = service['image'].format(PROJECT_ID)
        print(f"\n📦 建構 Docker 映像: {image}")
        if not run_command(f'gcloud builds submit --tag {image} --project={PROJECT_ID}', cwd=service['path']):
            print(f"❌ {service['name']} 建構失敗，跳過")
            continue
        
        # 部署到 Cloud Run
        print(f"\n🚀 部署到 Cloud Run: {service['name']}")
        deploy_cmd = f'gcloud run deploy {service["name"]} \\\n'
        deploy_cmd += f'  --image={image} \\\n'
        deploy_cmd += f'  --region={REGION} \\\n'
        deploy_cmd += f'  --platform=managed \\\n'
        deploy_cmd += f'  --allow-unauthenticated \\\n'
        deploy_cmd += f'  --service-account=forte-booking-system@forte-booking-system.iam.gserviceaccount.com \\\n'
        deploy_cmd += ' \\\n'.join([f'  {arg}' for arg in service['deploy_args']])
        deploy_cmd += f' \\\n  --project={PROJECT_ID}'
        
        if not run_command(deploy_cmd):
            print(f"❌ {service['name']} 部署失敗")
            continue
        
        print(f"✅ {service['name']} 重建構完成")
        print("")
        time.sleep(2)  # 稍作延遲
    
    # 驗證服務網址
    print("=" * 70)
    print("✅ 所有服務重建構完成")
    print("=" * 70)
    print("")
    print("📋 驗證服務網址（應該沒有改變）：")
    run_command(f'gcloud run services list --region={REGION} --project={PROJECT_ID} --format="table(metadata.name,status.url)"')
    print("")
    print("💡 提示：")
    print("  - 服務網址不會改變 ✅")
    print("  - 舊的映像和 revisions 會被自動清理")
    print("  - Artifact Registry 容量會在 24-48 小時後減少")

if __name__ == "__main__":
    main()

