# 当前路由与存储索引

由 `tests/inspect_contract.py` 在临时新数据库中实例化当前 Flask 应用生成。只含结构，不含运行数据或凭据。

本表描述**本地源码**，其与正式版本的差异见 [交接说明](HANDOFF.md)。表用于定位代码；字段、权限、错误和状态机参见 [README 文档导航](../README.md#文档导航)。

Flask HTTP 方法与路径组合：**156**；另有 `GET /space/<slug>`。HEAD/OPTIONS 不重复列出。动态 `<action>` 路由算一个模板，允许的具体动作见 [待办发布契约](TASK-PUBLISH.md)。

| 方法 | 路径 | 实现 |
|---|---|---|
| GET | `/` | [app.py](../app.py) · `index` |
| GET | `/api/accounts` | [cloud_accounts.py](../cloud_accounts.py) · `accounts` |
| DELETE | `/api/accounts/<account_id>` | [cloud_accounts.py](../cloud_accounts.py) · `disconnect` |
| GET | `/api/accounts/<account_id>/sources` | [cloud_accounts.py](../cloud_accounts.py) · `sources` |
| POST | `/api/accounts/<account_id>/sources` | [cloud_accounts.py](../cloud_accounts.py) · `sources` |
| POST | `/api/accounts/<account_id>/sync` | [cloud_accounts.py](../cloud_accounts.py) · `sync_now` |
| POST | `/api/accounts/bind` | [cloud_accounts.py](../cloud_accounts.py) · `bind` |
| POST | `/api/accounts/google-photos/bind` | [cloud_accounts.py](../cloud_accounts.py) · `bind_google_photos` |
| GET | `/api/assistant/brief` | [home_assistant.py](../home_assistant.py) · `get_brief` |
| POST | `/api/assistant/journey-brief` | [home_assistant.py](../home_assistant.py) · `journey_brief` |
| POST | `/api/assistant/plan` | [home_assistant.py](../home_assistant.py) · `plan` |
| POST | `/api/assistant/plans/<uid>/apply` | [home_assistant.py](../home_assistant.py) · `apply_plan` |
| GET | `/api/assistant/search` | [home_assistant.py](../home_assistant.py) · `search` |
| GET | `/api/auth/providers` | [cloud_accounts.py](../cloud_accounts.py) · `providers` |
| POST | `/api/calendar-publish/authorize` | [calendar_publish.py](../calendar_publish.py) · `publication_authorize` |
| POST | `/api/calendar-publish/confirm` | [calendar_publish.py](../calendar_publish.py) · `publication_confirm` |
| GET | `/api/calendar-publish/journeys/<journey_id>` | [calendar_publish.py](../calendar_publish.py) · `publication_state` |
| POST | `/api/calendar-publish/preview` | [calendar_publish.py](../calendar_publish.py) · `publication_preview` |
| POST | `/api/calendar-publish/publications/<rid>/conflict-confirm` | [calendar_publish.py](../calendar_publish.py) · `publication_conflict_confirm` |
| POST | `/api/calendar-publish/publications/<rid>/conflict-preview` | [calendar_publish.py](../calendar_publish.py) · `publication_conflict_preview` |
| POST | `/api/calendar-publish/publications/<rid>/pause` | [calendar_publish.py](../calendar_publish.py) · `publication_pause` |
| POST | `/api/calendar-publish/publications/<rid>/resume` | [calendar_publish.py](../calendar_publish.py) · `publication_resume` |
| POST | `/api/calendar-publish/publications/<rid>/retry` | [calendar_publish.py](../calendar_publish.py) · `publication_retry` |
| POST | `/api/calendar-publish/publications/<rid>/review-confirm` | [calendar_publish.py](../calendar_publish.py) · `publication_review_confirm` |
| POST | `/api/calendar-publish/publications/<rid>/review-preview` | [calendar_publish.py](../calendar_publish.py) · `publication_review_preview` |
| POST | `/api/calendar/import` | [app.py](../app.py) · `calendar_import` |
| GET | `/api/dashboard-layout` | [dashboard_preferences.py](../dashboard_preferences.py) · `dashboard_layout` |
| PUT | `/api/dashboard-layout` | [dashboard_preferences.py](../dashboard_preferences.py) · `dashboard_layout` |
| GET | `/api/devices` | [app.py](../app.py) · `devices` |
| DELETE | `/api/devices/<uid>` | [app.py](../app.py) · `revoke_device` |
| PATCH | `/api/devices/<uid>` | [app.py](../app.py) · `edit_device` |
| PUT | `/api/finance` | [app.py](../app.py) · `finance_update` |
| POST | `/api/finance-baseline/imports/confirm` | [finance_source_bridge.py](../finance_source_bridge.py) · `finance_source_confirm` |
| POST | `/api/finance-baseline/imports/preview` | [finance_source_bridge.py](../finance_source_bridge.py) · `finance_source_preview` |
| GET | `/api/finance-baseline/imports/status` | [finance_source_bridge.py](../finance_source_bridge.py) · `finance_source_status` |
| GET | `/api/finance-baseline/private` | [finance_baseline.py](../finance_baseline.py) · `private_baseline` |
| PUT | `/api/finance-hub/budgets` | [finance_hub.py](../finance_hub.py) · `hub_put_budget` |
| POST | `/api/finance-hub/imports/confirm` | [finance_hub.py](../finance_hub.py) · `hub_confirm` |
| POST | `/api/finance-hub/imports/preview` | [finance_hub.py](../finance_hub.py) · `hub_preview` |
| GET | `/api/finance-hub/imports/results/<request_id>` | [finance_hub.py](../finance_hub.py) · `hub_import_result` |
| GET | `/api/finance-hub/investments` | [investment_operations.py](../investment_operations.py) · `investment_current` |
| POST | `/api/finance-hub/investments` | [finance_hub.py](../finance_hub.py) · `hub_create_investment` |
| DELETE | `/api/finance-hub/investments/<rid>` | [finance_hub.py](../finance_hub.py) · `hub_delete_investment` |
| PATCH | `/api/finance-hub/investments/<rid>` | [finance_hub.py](../finance_hub.py) · `hub_update_investment` |
| POST | `/api/finance-hub/investments/imports/confirm` | [investment_import.py](../investment_import.py) · `investment_import_confirm` |
| POST | `/api/finance-hub/investments/imports/preview` | [investment_import.py](../investment_import.py) · `investment_import_preview` |
| GET | `/api/finance-hub/investments/imports/receipts` | [investment_import.py](../investment_import.py) · `investment_import_receipt` |
| GET | `/api/finance-hub/investments/imports/template` | [investment_import.py](../investment_import.py) · `investment_import_template` |
| GET | `/api/finance-hub/investments/operations/<rid>` | [investment_operations.py](../investment_operations.py) · `investment_operation_result` |
| GET | `/api/finance-hub/overview` | [finance_hub.py](../finance_hub.py) · `hub_overview` |
| GET | `/api/finance-hub/reconciliation` | [finance_hub.py](../finance_hub.py) · `hub_reconciliation` |
| POST | `/api/finance-hub/reconciliation/<rid>/revoke` | [finance_hub.py](../finance_hub.py) · `hub_reconciliation_revoke` |
| POST | `/api/finance-hub/reconciliation/confirm` | [finance_hub.py](../finance_hub.py) · `hub_reconciliation_confirm` |
| POST | `/api/finance-hub/reconciliation/preview` | [finance_hub.py](../finance_hub.py) · `hub_reconciliation_preview` |
| GET | `/api/finance-hub/shared` | [finance_hub.py](../finance_hub.py) · `hub_shared` |
| POST | `/api/finance-hub/shopping-settlements/confirm` | [shopping_settlement.py](../shopping_settlement.py) · `settlement_confirm` |
| GET | `/api/finance-hub/shopping-settlements/context` | [shopping_settlement.py](../shopping_settlement.py) · `settlement_context` |
| POST | `/api/finance-hub/shopping-settlements/preview` | [shopping_settlement.py](../shopping_settlement.py) · `settlement_preview` |
| GET | `/api/finance-hub/template` | [finance_hub.py](../finance_hub.py) · `hub_template` |
| GET | `/api/finance-hub/transactions` | [finance_hub.py](../finance_hub.py) · `hub_transactions` |
| DELETE | `/api/finance-hub/transactions/<rid>` | [finance_hub.py](../finance_hub.py) · `hub_delete_transaction` |
| PATCH | `/api/finance-hub/transactions/<rid>` | [finance_hub.py](../finance_hub.py) · `hub_patch_transaction` |
| GET | `/api/inventory/acquisitions/<uid>` | [inventory_api.py](../inventory_api.py) · `inventory_acquisition` |
| PATCH | `/api/inventory/acquisitions/<uid>` | [inventory_api.py](../inventory_api.py) · `inventory_acquisition` |
| GET | `/api/inventory/acquisitions/<uid>/movements` | [inventory_api.py](../inventory_api.py) · `inventory_movements` |
| POST | `/api/inventory/acquisitions/<uid>/movements` | [inventory_api.py](../inventory_api.py) · `inventory_movements` |
| POST | `/api/inventory/acquisitions/<uid>/movements/<movement_id>/reverse` | [inventory_api.py](../inventory_api.py) · `inventory_reverse` |
| GET | `/api/inventory/items` | [inventory_api.py](../inventory_api.py) · `inventory_items` |
| POST | `/api/inventory/items` | [inventory_api.py](../inventory_api.py) · `inventory_items` |
| DELETE | `/api/inventory/items/<uid>` | [inventory_api.py](../inventory_api.py) · `inventory_item` |
| GET | `/api/inventory/items/<uid>` | [inventory_api.py](../inventory_api.py) · `inventory_item` |
| PATCH | `/api/inventory/items/<uid>` | [inventory_api.py](../inventory_api.py) · `inventory_item` |
| GET | `/api/inventory/items/<uid>/acquisitions` | [inventory_api.py](../inventory_api.py) · `inventory_acquisitions` |
| POST | `/api/inventory/items/<uid>/acquisitions` | [inventory_api.py](../inventory_api.py) · `inventory_acquisitions` |
| GET | `/api/inventory/operations/<request_id>` | [inventory_api.py](../inventory_api.py) · `inventory_operation` |
| POST | `/api/items/<kind>` | [app.py](../app.py) · `add_item` |
| DELETE | `/api/items/<kind>/<uid>` | [app.py](../app.py) · `delete_item` |
| PATCH | `/api/items/<kind>/<uid>` | [app.py](../app.py) · `edit_item` |
| GET | `/api/journey-documents` | [journey_documents.py](../journey_documents.py) · `list_journey_documents` |
| POST | `/api/journey-documents` | [journey_documents.py](../journey_documents.py) · `upload_journey_document` |
| DELETE | `/api/journey-documents/<document_id>` | [journey_documents.py](../journey_documents.py) · `delete_journey_document` |
| PATCH | `/api/journey-documents/<document_id>` | [journey_documents.py](../journey_documents.py) · `update_journey_document` |
| GET | `/api/journey-documents/<document_id>/file` | [journey_documents.py](../journey_documents.py) · `download_journey_document` |
| GET | `/api/journey-places` | [journey_places.py](../journey_places.py) · `list_journey_places` |
| POST | `/api/journey-places` | [journey_places.py](../journey_places.py) · `create_journey_place` |
| DELETE | `/api/journey-places/<uid>` | [journey_places.py](../journey_places.py) · `delete_journey_place` |
| GET | `/api/journey-places/<uid>` | [journey_places.py](../journey_places.py) · `get_journey_place` |
| PATCH | `/api/journey-places/<uid>` | [journey_places.py](../journey_places.py) · `update_journey_place` |
| GET | `/api/journeys` | [journey_workflows.py](../journey_workflows.py) · `journey_list` |
| GET | `/api/journeys/<uid>` | [journey_workflows.py](../journey_workflows.py) · `journey_detail` |
| GET | `/api/journeys/<uid>/calendar` | [journey_workflows.py](../journey_workflows.py) · `journey_calendar` |
| GET | `/api/journeys/<uid>/calendar.ics` | [journey_workflows.py](../journey_workflows.py) · `journey_calendar_ics` |
| GET | `/api/journeys/<uid>/reschedule` | [journey_workflows.py](../journey_workflows.py) · `journey_reschedule_snapshot` |
| POST | `/api/journeys/<uid>/reschedule-preview` | [journey_workflows.py](../journey_workflows.py) · `journey_reschedule_preview` |
| POST | `/api/journeys/apply` | [journey_workflows.py](../journey_workflows.py) · `journey_apply` |
| GET | `/api/journeys/operations/<key>` | [journey_workflows.py](../journey_workflows.py) · `journey_operation_result` |
| POST | `/api/journeys/preview` | [journey_workflows.py](../journey_workflows.py) · `journey_preview` |
| GET | `/api/journeys/templates` | [journey_workflows.py](../journey_workflows.py) · `journey_templates` |
| POST | `/api/login` | [app.py](../app.py) · `login` |
| POST | `/api/logout` | [app.py](../app.py) · `logout` |
| GET | `/api/me` | [app.py](../app.py) · `me` |
| GET | `/api/media-playback/devices/<uid>` | [media_playback.py](../media_playback.py) · `media_playback_control` |
| PUT | `/api/media-playback/devices/<uid>` | [media_playback.py](../media_playback.py) · `media_playback_control` |
| GET | `/api/media-tv/items` | [household_media.py](../household_media.py) · `media_tv_items` |
| GET | `/api/media-tv/items/<uid>/preview` | [household_media.py](../household_media.py) · `media_tv_preview` |
| GET | `/api/media-tv/playback` | [media_playback.py](../media_playback.py) · `media_playback_tv` |
| GET | `/api/media/imports` | [household_media.py](../household_media.py) · `media_imports` |
| POST | `/api/media/imports` | [household_media.py](../household_media.py) · `media_imports` |
| DELETE | `/api/media/imports/<uid>` | [household_media.py](../household_media.py) · `media_import_detail` |
| GET | `/api/media/imports/<uid>` | [household_media.py](../household_media.py) · `media_import_detail` |
| POST | `/api/media/imports/<uid>/confirm` | [household_media.py](../household_media.py) · `media_import_confirm` |
| GET | `/api/media/items` | [household_media.py](../household_media.py) · `media_items` |
| DELETE | `/api/media/items/<uid>` | [household_media.py](../household_media.py) · `media_item` |
| GET | `/api/media/items/<uid>` | [household_media.py](../household_media.py) · `media_item` |
| PATCH | `/api/media/items/<uid>` | [household_media.py](../household_media.py) · `media_item` |
| GET | `/api/media/items/<uid>/journey-suggestions` | [household_media.py](../household_media.py) · `media_journey_suggestions` |
| GET | `/api/media/items/<uid>/preview` | [household_media.py](../household_media.py) · `media_preview` |
| GET | `/api/media/items/<uid>/tv-grants` | [household_media.py](../household_media.py) · `media_tv_grants` |
| PUT | `/api/media/items/<uid>/tv-grants` | [household_media.py](../household_media.py) · `media_tv_grants` |
| POST | `/api/pair/approve` | [app.py](../app.py) · `pair_approve` |
| POST | `/api/pair/poll` | [app.py](../app.py) · `pair_poll` |
| POST | `/api/pair/start` | [app.py](../app.py) · `pair_start` |
| POST | `/api/photos` | [shopping_media.py](../shopping_media.py) · `upload_photo` |
| GET | `/api/photos/<uid>` | [shopping_media.py](../shopping_media.py) · `get_photo` |
| POST | `/api/portability/export` | [data_portability.py](../data_portability.py) · `export_data` |
| GET | `/api/portability/summary` | [data_portability.py](../data_portability.py) · `export_summary` |
| GET | `/api/preferences` | [household_spaces.py](../household_spaces.py) · `preferences` |
| PUT | `/api/preferences` | [household_spaces.py](../household_spaces.py) · `preferences` |
| GET | `/api/private-finance` | [app.py](../app.py) · `private_finance` |
| PUT | `/api/private-finance` | [app.py](../app.py) · `private_finance` |
| POST | `/api/profile` | [app.py](../app.py) · `profile` |
| POST | `/api/routines/confirm` | [household_routines.py](../household_routines.py) · `routine_confirm` |
| GET | `/api/routines/context` | [household_routines.py](../household_routines.py) · `routine_context` |
| GET | `/api/routines/operations/<operation_key>` | [household_routines.py](../household_routines.py) · `routine_operation` |
| POST | `/api/routines/preview` | [household_routines.py](../household_routines.py) · `routine_preview` |
| GET | `/api/sessions` | [member_sessions.py](../member_sessions.py) · `sessions_list` |
| DELETE | `/api/sessions/<session_id>` | [member_sessions.py](../member_sessions.py) · `session_delete` |
| POST | `/api/sessions/revoke-others` | [member_sessions.py](../member_sessions.py) · `sessions_revoke_others` |
| GET | `/api/spaces/current` | [household_spaces.py](../household_spaces.py) · `current_space` |
| POST | `/api/spaces/invitations` | [household_spaces.py](../household_spaces.py) · `invite_household` |
| POST | `/api/spaces/redeem` | [household_spaces.py](../household_spaces.py) · `redeem_household` |
| GET | `/api/state` | [app.py](../app.py) · `state` |
| GET | `/api/sync-health` | [sync_health.py](../sync_health.py) · `sync_health` |
| POST | `/api/task-publish/confirm` | [task_publish.py](../task_publish.py) · `task_publication_confirm` |
| POST | `/api/task-publish/preview` | [task_publish.py](../task_publish.py) · `task_publication_preview` |
| POST | `/api/task-publish/publications/<rid>/<action>` | [task_publish.py](../task_publish.py) · `task_publication_action` |
| GET | `/api/task-publish/state` | [task_publish.py](../task_publish.py) · `task_publication_state` |
| GET | `/app` | [frontend_runtime.py](../frontend_runtime.py) · `expo_frontend` |
| GET | `/app/<path:name>` | [frontend_runtime.py](../frontend_runtime.py) · `expo_frontend` |
| GET | `/auth/<provider>/callback` | [cloud_accounts.py](../cloud_accounts.py) · `callback` |
| GET | `/auth/<provider>/login` | [cloud_accounts.py](../cloud_accounts.py) · `external_login` |
| GET | `/classic` | [frontend_runtime.py](../frontend_runtime.py) · `classic_frontend` |
| GET | `/demo` | [app.py](../app.py) · `index` |
| GET | `/healthz` | [app.py](../app.py) · `health` |
| GET | `/static/<path:name>` | [app.py](../app.py) · `asset` |
| GET | `/tv` | [frontend_runtime.py](../frontend_runtime.py) · `television_frontend` |

## 每户业务数据表

共 **55** 张表：

`assistant_plans`, `attempts`, `audit`, `calendar_publications`, `cloud_accounts`, `cloud_items`, `cloud_oauth_states`, `cloud_sources`, `cloud_writes`, `devices`, `entities`, `finance_baselines`, `finance_source_receipts`, `finance_spending_observations`, `finance_spending_receipts`, `household_routines`, `hub_budgets`, `hub_import_receipts`, `hub_imports`, `hub_investment_import_previews`, `hub_investment_import_receipts`, `hub_investment_links`, `hub_investment_operations`, `hub_investment_sources`, `hub_investments`, `hub_reconciliations`, `hub_shopping_settlement_receipts`, `hub_shopping_settlements`, `hub_transactions`, `inventory_acquisitions`, `inventory_items`, `inventory_movements`, `inventory_operations`, `inventory_source_links`, `journey_actions`, `journey_documents`, `journey_links`, `journey_places`, `journey_workflows`, `media_imports`, `media_items`, `media_playback`, `media_tv_grants`, `member_dashboard_layout`, `member_preferences`, `member_session_browsers`, `member_sessions`, `photo_refs`, `photos`, `private_finance`, `routine_occurrences`, `routine_receipts`, `settings`, `task_publications`, `users`

## 平台注册目录

共 **2** 张表：

`household_invitations`, `households`

每户表位于各自 `household.sqlite3`；平台注册目录位于 `platform.sqlite3`。字段结构见 [机器可读清单](contract-inventory.json)。

重建本索引：在隔离开发环境运行 `python tests/inspect_contract.py`。该脚本只写本文及相邻 JSON，使用虚构初始密码和临时数据库，不读取 `.env`，不连接第三方服务。
