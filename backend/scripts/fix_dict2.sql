INSERT INTO dict_items (dict_id, item_value, item_label, sort_order, status, created_at, updated_at)
SELECT id, 'CASE_GEN', 'Agent 用例生成', 12, 'ACTIVE', NOW(), NOW() FROM data_dicts WHERE dict_code='case_category'
AND NOT EXISTS (SELECT 1 FROM dict_items WHERE dict_id=(SELECT id FROM data_dicts WHERE dict_code='case_category') AND item_value='CASE_GEN');

INSERT INTO dict_items (dict_id, item_value, item_label, sort_order, status, created_at, updated_at)
SELECT id, 'SELF_HEAL', '脚本自愈', 13, 'ACTIVE', NOW(), NOW() FROM data_dicts WHERE dict_code='case_category'
AND NOT EXISTS (SELECT 1 FROM dict_items WHERE dict_id=(SELECT id FROM data_dicts WHERE dict_code='case_category') AND item_value='SELF_HEAL');

INSERT INTO dict_items (dict_id, item_value, item_label, sort_order, status, created_at, updated_at)
SELECT id, 'DEFECT_PREDICT', '缺陷预测', 14, 'ACTIVE', NOW(), NOW() FROM data_dicts WHERE dict_code='case_category'
AND NOT EXISTS (SELECT 1 FROM dict_items WHERE dict_id=(SELECT id FROM data_dicts WHERE dict_code='case_category') AND item_value='DEFECT_PREDICT');

INSERT INTO dict_items (dict_id, item_value, item_label, sort_order, status, created_at, updated_at)
SELECT id, 'DATAFLOW', '数据流测试', 14, 'ACTIVE', NOW(), NOW() FROM data_dicts WHERE dict_code='TEST_CATEGORY'
AND NOT EXISTS (SELECT 1 FROM dict_items WHERE dict_id=(SELECT id FROM data_dicts WHERE dict_code='TEST_CATEGORY') AND item_value='DATAFLOW');

INSERT INTO dict_items (dict_id, item_value, item_label, sort_order, status, created_at, updated_at)
SELECT id, 'EVAL', '平台化评测', 15, 'ACTIVE', NOW(), NOW() FROM data_dicts WHERE dict_code='TEST_CATEGORY'
AND NOT EXISTS (SELECT 1 FROM dict_items WHERE dict_id=(SELECT id FROM data_dicts WHERE dict_code='TEST_CATEGORY') AND item_value='EVAL');

SELECT d.dict_code, count(*) FROM dict_items di JOIN data_dicts d ON di.dict_id=d.id WHERE di.status='ACTIVE' AND d.dict_code IN ('case_category','TEST_CATEGORY') GROUP BY d.dict_code;
