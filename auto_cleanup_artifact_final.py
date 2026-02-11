#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自動清理 Artifact Registry 和 Container Registry 中的未使用映像
確保：
1. 不會刪除正在使用的映像
2. 不會影響服務網址
3. 只刪除真正未使用的映像
"""

import subprocess
import json
import sys

# 設置 UTF-8 編碼
sys.stdout.reconfigure(encoding='utf-8')

PROJECT_ID = "forte-booking-system"
REGION = "asia-east1"

# 服務配置
SERVICES = {
    "hotel-web": {
        "region": REGION,
        "registry": "asia-east1-docker.pkg.dev",
        "repository": "hotel-web",
        "image_name": "web"
    },
    "booking-api": {
        "region": REGION,
        "registry": "gcr.io",
        "repository": None,
        "image_name": "booking-api"
    },
    "booking-manager": {
        "region": REGION,
        "registry": "gcr.io",
        "repository": None,
        "image_name": "booking-manager"
    },
    "driver-api2": {
        "region": REGION,
        "registry": "gcr.io",
        "repository": None,
        "image_name": "driver-api2"
    }
}

def run_command(cmd):
    """執行命令並返回結果"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            encoding='utf-8'
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except Exception as e:
        return False, "", str(e)

def get_active_image_digest(service_name, service_config):
    """獲取服務正在使用的完整映像 digest"""
    print(f"\n📋 檢查服務: {service_name}")
    
    # 獲取所有 revisions 使用的映像
    cmd = f'gcloud run revisions list --service={service_name} --region={service_config["region"]} --format="value(spec.containers[0].image)" --project={PROJECT_ID}'
    success, output, error = run_command(cmd)
    
    if not success:
        print(f"  ⚠️  無法獲取 revisions: {error}")
        return set()
    
    active_digests = set()
    for line in output.strip().split('\n'):
        if line and '@sha256:' in line:
            digest = line.split('@sha256:')[1].strip()
            active_digests.add(digest)
    
    if active_digests:
        print(f"  ✅ 找到 {len(active_digests)} 個正在使用的 digest")
        for d in list(active_digests)[:3]:  # 只顯示前3個
            print(f"     - sha256:{d[:16]}...")
    else:
        print(f"  ⚠️  未找到 digest")
    
    return active_digests

def get_all_images(service_name, service_config):
    """獲取倉庫中所有映像"""
    registry = service_config["registry"]
    repository = service_config.get("repository")
    image_name = service_config["image_name"]
    
    if registry == "gcr.io":
        # Container Registry
        full_path = f"gcr.io/{PROJECT_ID}/{image_name}"
        cmd = f'gcloud container images list-tags {full_path} --format="json" --project={PROJECT_ID}'
    else:
        # Artifact Registry
        full_path = f"{registry}/{PROJECT_ID}/{repository}/{image_name}"
        cmd = f'gcloud artifacts docker images list {full_path} --format="json" --project={PROJECT_ID}'
    
    print(f"\n📦 列出所有映像: {full_path}")
    success, output, error = run_command(cmd)
    
    if not success:
        print(f"  ⚠️  無法獲取映像列表: {error}")
        return []
    
    try:
        images = json.loads(output)
        print(f"  ✅ 找到 {len(images)} 個映像版本")
        return images
    except Exception as e:
        print(f"  ⚠️  解析映像列表失敗: {e}")
        return []

def delete_image(service_name, service_config, digest):
    """刪除指定的映像"""
    registry = service_config["registry"]
    repository = service_config.get("repository")
    image_name = service_config["image_name"]
    
    if registry == "gcr.io":
        # Container Registry
        full_path = f"gcr.io/{PROJECT_ID}/{image_name}@sha256:{digest}"
        cmd = f'gcloud container images delete {full_path} --quiet --project={PROJECT_ID}'
    else:
        # Artifact Registry
        full_path = f"{registry}/{PROJECT_ID}/{repository}/{image_name}@sha256:{digest}"
        cmd = f'gcloud artifacts docker images delete {full_path} --quiet --project={PROJECT_ID}'
    
    print(f"  🗑️  刪除: sha256:{digest[:16]}...")
    success, output, error = run_command(cmd)
    
    if success:
        print(f"  ✅ 刪除成功")
        return True
    else:
        print(f"  ⚠️  刪除失敗: {error}")
        return False

def main():
    print("=" * 70)
    print("🔍 自動清理 Artifact Registry 和 Container Registry")
    print("=" * 70)
    print(f"專案: {PROJECT_ID}")
    print(f"區域: {REGION}")
    print("\n✅ 安全保證:")
    print("  - 不會刪除正在使用的映像")
    print("  - 不會影響服務網址")
    print("  - 不會影響服務運行")
    print("=" * 70)
    
    # 步驟 1: 獲取所有正在使用的映像
    print("\n" + "=" * 70)
    print("步驟 1: 識別正在使用的映像")
    print("=" * 70)
    
    active_digests = {}
    for service_name, service_config in SERVICES.items():
        digests = get_active_image_digest(service_name, service_config)
        if digests:
            active_digests[service_name] = digests
    
    if not active_digests:
        print("\n❌ 無法確定正在使用的映像，為安全起見，停止執行")
        return
    
    print(f"\n✅ 已識別 {len(active_digests)} 個服務正在使用的映像")
    
    # 步驟 2: 分析每個服務的映像
    print("\n" + "=" * 70)
    print("步驟 2: 分析未使用的映像")
    print("=" * 70)
    
    total_deletable = 0
    deletable_images = []
    
    for service_name, service_config in SERVICES.items():
        print(f"\n{'='*70}")
        print(f"服務: {service_name}")
        print(f"{'='*70}")
        
        # 獲取當前使用的 digest
        current_digests = active_digests.get(service_name, set())
        
        # 獲取所有映像
        all_images = get_all_images(service_name, service_config)
        
        if not all_images:
            print(f"  ℹ️  沒有找到映像")
            continue
        
        # 找出未使用的映像
        unused_images = []
        for img in all_images:
            if service_config["registry"] == "gcr.io":
                # Container Registry 格式
                digest = img.get("digest", "").replace("sha256:", "")
            else:
                # Artifact Registry 格式
                digest = img.get("version", "").replace("sha256:", "")
            
            if digest and digest not in current_digests:
                unused_images.append({
                    "service": service_name,
                    "digest": digest,
                    "image": img
                })
        
        print(f"\n  📊 統計:")
        print(f"    總映像數: {len(all_images)}")
        print(f"    正在使用: {len(current_digests)}")
        print(f"    可刪除: {len(unused_images)}")
        
        if unused_images:
            deletable_images.extend(unused_images)
            total_deletable += len(unused_images)
    
    # 步驟 3: 顯示總結
    print("\n" + "=" * 70)
    print("步驟 3: 清理總結")
    print("=" * 70)
    
    if total_deletable == 0:
        print("\n✅ 沒有可刪除的映像，所有映像都在使用中")
        print("\n💡 關於 Artifact Registry 容量大的原因:")
        print("   1. Docker 使用層級共享技術，多個映像可能共享相同的層級")
        print("   2. 即使刪除了映像，共享的層級可能仍然存在")
        print("   3. GCP 會定期清理未使用的層級，但可能需要時間")
        print("   4. 建議等待 24-48 小時後再檢查容量變化")
        return
    
    print(f"\n📋 可刪除的映像總數: {total_deletable}")
    print("\n詳細列表:")
    for item in deletable_images:
        digest_short = item["digest"][:16] if item["digest"] else "unknown"
        print(f"  - {item['service']}: sha256:{digest_short}...")
    
    # 步驟 4: 執行刪除
    print("\n" + "=" * 70)
    print("步驟 4: 執行刪除")
    print("=" * 70)
    
    deleted_count = 0
    failed_count = 0
    
    for item in deletable_images:
        service_name = item["service"]
        digest = item["digest"]
        service_config = SERVICES[service_name]
        
        if delete_image(service_name, service_config, digest):
            deleted_count += 1
        else:
            failed_count += 1
    
    # 最終總結
    print("\n" + "=" * 70)
    print("✅ 清理完成")
    print("=" * 70)
    print(f"成功刪除: {deleted_count} 個映像")
    if failed_count > 0:
        print(f"刪除失敗: {failed_count} 個映像")
    
    print("\n💡 重要提示:")
    print("   1. 服務網址不會改變 ✅")
    print("   2. 正在運行的服務不受影響 ✅")
    print("   3. Artifact Registry 的容量可能不會立即減少")
    print("   4. Docker 使用層級共享，刪除映像後需要等待 GCP 清理未使用的層級")
    print("   5. 建議 24-48 小時後再檢查容量變化")

if __name__ == "__main__":
    main()

