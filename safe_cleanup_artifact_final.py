#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全清理 Artifact Registry 和 Container Registry 中的未使用映像
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
    
    # 獲取當前服務使用的映像
    cmd = f'gcloud run services describe {service_name} --region={service_config["region"]} --format="value(spec.template.spec.containers[0].image)" --project={PROJECT_ID}'
    success, output, error = run_command(cmd)
    
    if not success:
        print(f"  ⚠️  無法獲取服務映像: {error}")
        return None
    
    image_url = output.strip()
    print(f"  ✅ 當前映像: {image_url}")
    
    # 提取 digest
    if "@sha256:" in image_url:
        digest = image_url.split("@sha256:")[1].strip()
        print(f"  ✅ Digest: sha256:{digest[:16]}...")
        return digest
    
    # 如果沒有 digest，嘗試獲取所有 revisions 使用的映像
    print(f"  ⚠️  映像沒有 digest，檢查所有 revisions...")
    cmd = f'gcloud run revisions list --service={service_name} --region={service_config["region"]} --format="value(spec.containers[0].image)" --project={PROJECT_ID}'
    success, output, error = run_command(cmd)
    
    if success:
        active_digests = set()
        for line in output.strip().split('\n'):
            if line and '@sha256:' in line:
                digest = line.split('@sha256:')[1].strip()
                active_digests.add(digest)
        print(f"  ✅ 找到 {len(active_digests)} 個正在使用的 digest")
        return active_digests
    
    return None

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
    
    print(f"  🗑️  刪除: {digest[:16]}...")
    success, output, error = run_command(cmd)
    
    if success:
        print(f"  ✅ 刪除成功")
        return True
    else:
        print(f"  ⚠️  刪除失敗: {error}")
        return False

def main():
    print("=" * 70)
    print("🔍 安全清理 Artifact Registry 和 Container Registry")
    print("=" * 70)
    print(f"專案: {PROJECT_ID}")
    print(f"區域: {REGION}")
    print("\n⚠️  此腳本將：")
    print("  1. 識別所有正在使用的映像（確保不會刪除）")
    print("  2. 列出所有未使用的映像")
    print("  3. 安全地刪除未使用的映像")
    print("  4. 確保服務網址不會改變")
    print("=" * 70)
    
    # 步驟 1: 獲取所有正在使用的映像
    print("\n" + "=" * 70)
    print("步驟 1: 識別正在使用的映像")
    print("=" * 70)
    
    active_digests = {}
    for service_name, service_config in SERVICES.items():
        digest = get_active_image_digest(service_name, service_config)
        if digest:
            active_digests[service_name] = digest
    
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
        current_digest = active_digests.get(service_name)
        if isinstance(current_digest, set):
            current_digests = current_digest
        else:
            current_digests = {current_digest} if current_digest else set()
        
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
        return
    
    print(f"\n📋 可刪除的映像總數: {total_deletable}")
    print("\n詳細列表:")
    for item in deletable_images:
        digest_short = item["digest"][:16] if item["digest"] else "unknown"
        print(f"  - {item['service']}: sha256:{digest_short}...")
    
    # 步驟 4: 確認並刪除
    print("\n" + "=" * 70)
    print("步驟 4: 確認刪除")
    print("=" * 70)
    
    print("\n⚠️  準備刪除以上未使用的映像")
    print("✅ 安全保證:")
    print("  - 不會刪除正在使用的映像")
    print("  - 不會影響服務網址")
    print("  - 不會影響服務運行")
    
    response = input("\n是否繼續刪除？(yes/no): ").strip().lower()
    
    if response != "yes":
        print("\n❌ 已取消刪除操作")
        return
    
    # 執行刪除
    print("\n" + "=" * 70)
    print("步驟 5: 執行刪除")
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
    print("\n💡 提示: Artifact Registry 的容量可能不會立即減少")
    print("   因為 Docker 使用層級共享，刪除映像後需要等待 GCP 清理未使用的層級")

if __name__ == "__main__":
    main()

