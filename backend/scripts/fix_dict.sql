ALTER TABLE dict_items ALTER COLUMN created_at SET DEFAULT NOW();
ALTER TABLE dict_items ALTER COLUMN updated_at SET DEFAULT NOW();
INSERT INTO dict_items (dict_id, item_value, item_label, sort_order, status, created_at, updated_at) SELECT id, 'DATAFLOW', '数据流测试', 9, 'ACTIVE', NOW(), NOW() FROM data_dicts WHERE dict_code='case_category' ON CONFLICT DO NOTHING;
INSERT INTO dict_items (dict_id, item_value, item_label, sort_order, status, created_at, updated_at) SELECT id, 'MULTITURN', '多轮一致性', 10, 'ACTIVE', NOW(), NOW() FROM data_dicts WHERE dict_code='case_category' ON CONFLICT DO NOTHING;
INSERT INTO dict_items (dict_id, item_value, item_label, sort_order, status, created_at, updated_at) SELECT id, 'EVAL', '平台化评测', 11, 'ACTIVE', NOW(), NOW() FROM data_dicts WHERE dict_code='case_category' ON CONFLICT DO NOTHING;
SELECT count(*) as dict_items FROM dict_items WHERE dict_id=(SELECT id FROM data_dicts WHERE dict_code='case_category');
