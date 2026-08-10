--
-- PostgreSQL database dump
--

-- Dumped from database version 16.4
-- Dumped by pg_dump version 16.4

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Data for Name: pmcp_audit_log; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.pmcp_audit_log (trace_id, request_id, operator, skill_name, tool_name, resource_type, resource_id, env_code, request_summary, result_status, risk_level, error_code, error_message, start_time, end_time, duration_ms, extra_data, id, inserted_at, updated_at, inserted_by, updated_by) FROM stdin;
\.


--
-- Data for Name: pmcp_crypto_operation_log; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.pmcp_crypto_operation_log (operator, operation_type, datasource_code, algorithm, result_status, error_message, id, inserted_at, updated_at, inserted_by, updated_by) FROM stdin;
\.


--
-- Data for Name: pmcp_datasource; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.pmcp_datasource (datasource_code, datasource_name, db_type, host, port, instance_name, service_name, database, username, encrypted_password, env_code, status, max_concurrent, query_timeout, remark, id, inserted_at, updated_at, inserted_by, updated_by) FROM stdin;
\.


--
-- Data for Name: pmcp_role; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.pmcp_role (role_name, role_code, status, remark, id, inserted_at, updated_at, inserted_by, updated_by) FROM stdin;
系统管理员	admin	1	\N	1	2026-06-05 18:08:40.214399+08	2026-06-05 18:08:40.214399+08	system	\N
开发人员	developer	1	\N	2	2026-06-05 18:08:40.220403+08	2026-06-05 18:08:40.220403+08	system	\N
\.


--
-- Data for Name: pmcp_user; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.pmcp_user (username, password, nickname, email, status, id, inserted_at, updated_at, inserted_by, updated_by) FROM stdin;
admin	$2b$12$BbcnlpLG9XY1tSJoTX75IOl6mFz1PWKven0kAE8ufaOZCs/gcD6XS	系统管理员	\N	1	1	2026-06-05 18:08:40.198866+08	2026-06-05 18:08:40.198866+08	system	\N
\.


--
-- Data for Name: pmcp_datasource_permission; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.pmcp_datasource_permission (datasource_id, user_id, role_id, permission_type, id, inserted_at, updated_at, inserted_by, updated_by) FROM stdin;
\.


--
-- Data for Name: pmcp_mcp_call_log; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.pmcp_mcp_call_log (trace_id, tool_name, caller, datasource_code, env_code, input_summary, output_summary, result_status, error_code, error_message, duration_ms, confirm_token, extra_data, id, inserted_at, updated_at, inserted_by, updated_by) FROM stdin;
\.


--
-- Data for Name: pmcp_permission; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.pmcp_permission (permission_name, permission_code, resource_type, resource_path, parent_id, status, sort_order, id, inserted_at, updated_at, inserted_by, updated_by) FROM stdin;
\.


--
-- Data for Name: pmcp_role_permission; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.pmcp_role_permission (role_id, permission_id, id, inserted_at, updated_at, inserted_by, updated_by) FROM stdin;
\.


--
-- Data for Name: pmcp_skill; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.pmcp_skill (skill_code, skill_name, description, status, register_method, tool_count, id, inserted_at, updated_at, inserted_by, updated_by) FROM stdin;
\.


--
-- Data for Name: pmcp_system_config; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.pmcp_system_config (config_key, config_value, config_type, description, status, id, inserted_at, updated_at, inserted_by, updated_by) FROM stdin;
\.


--
-- Data for Name: pmcp_user_role; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.pmcp_user_role (user_id, role_id, id, inserted_at, updated_at, inserted_by, updated_by) FROM stdin;
1	1	1	2026-06-05 18:08:40.225261+08	2026-06-05 18:08:40.225261+08	system	\N
\.


--
-- Name: pmcp_audit_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.pmcp_audit_log_id_seq', 1, false);


--
-- Name: pmcp_crypto_operation_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.pmcp_crypto_operation_log_id_seq', 1, false);


--
-- Name: pmcp_datasource_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.pmcp_datasource_id_seq', 1, false);


--
-- Name: pmcp_datasource_permission_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.pmcp_datasource_permission_id_seq', 1, false);


--
-- Name: pmcp_mcp_call_log_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.pmcp_mcp_call_log_id_seq', 1, false);


--
-- Name: pmcp_permission_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.pmcp_permission_id_seq', 1, false);


--
-- Name: pmcp_role_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.pmcp_role_id_seq', 2, true);


--
-- Name: pmcp_role_permission_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.pmcp_role_permission_id_seq', 1, false);


--
-- Name: pmcp_skill_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.pmcp_skill_id_seq', 1, false);


--
-- Name: pmcp_system_config_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.pmcp_system_config_id_seq', 1, false);


--
-- Name: pmcp_user_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.pmcp_user_id_seq', 1, true);


--
-- Name: pmcp_user_role_id_seq; Type: SEQUENCE SET; Schema: public; Owner: -
--

SELECT pg_catalog.setval('public.pmcp_user_role_id_seq', 1, true);


--
-- PostgreSQL database dump complete
--

