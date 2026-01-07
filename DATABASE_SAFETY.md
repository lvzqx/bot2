# データベース安全性ガイド

## 定期的なバックアップ
```bash
# 手動バックアップ
/backup_database

# バックアップ一覧確認
/list_backups
```

## データベース状態確認
```bash
# 整合性チェック
/check_database

# 孤立データクリーンアップ
/cleanup_orphaned
```

## GitHub Actionsの改善点
- ✅ 自動バックアップ作成
- ✅ 新しいデータ優先
- ✅ コンフリクト解消
- ✅ 状態監視

## 緊急時の対応
1. **データ消失**: `/restore_backup` で復元
2. **コンフリクト**: `/check_database` で確認
3. **整理**: `/cleanup_orphaned` でクリーンアップ

## 推奨される運用
- 毎日 `/check_database` で状態確認
- 毎週 `/backup_database` でバックアップ
- 問題発見時は即時対応
