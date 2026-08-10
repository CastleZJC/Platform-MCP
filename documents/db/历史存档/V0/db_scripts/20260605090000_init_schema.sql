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

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


--
-- Name: pmcp_audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmcp_audit_log (
    trace_id character varying(64),
    request_id character varying(64),
    operator character varying(64),
    skill_name character varying(64),
    tool_name character varying(64),
    resource_type character varying(64),
    resource_id character varying(128),
    env_code character varying(32),
    request_summary text,
    result_status character varying(32),
    risk_level character varying(16),
    error_code character varying(32),
    error_message text,
    start_time timestamp with time zone,
    end_time timestamp with time zone,
    duration_ms bigint,
    extra_data jsonb,
    id bigint NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    inserted_by character varying(64),
    updated_by character varying(64)
);


--
-- Name: TABLE pmcp_audit_log; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.pmcp_audit_log IS '审计日志';


--
-- Name: COLUMN pmcp_audit_log.trace_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.trace_id IS '全链路追踪标识';


--
-- Name: COLUMN pmcp_audit_log.request_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.request_id IS '请求唯一标识';


--
-- Name: COLUMN pmcp_audit_log.operator; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.operator IS '操作人';


--
-- Name: COLUMN pmcp_audit_log.skill_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.skill_name IS 'Skill 名称';


--
-- Name: COLUMN pmcp_audit_log.tool_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.tool_name IS 'Tool 名称';


--
-- Name: COLUMN pmcp_audit_log.resource_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.resource_type IS '资源类型';


--
-- Name: COLUMN pmcp_audit_log.resource_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.resource_id IS '资源标识';


--
-- Name: COLUMN pmcp_audit_log.env_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.env_code IS '环境标识';


--
-- Name: COLUMN pmcp_audit_log.request_summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.request_summary IS '请求摘要';


--
-- Name: COLUMN pmcp_audit_log.result_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.result_status IS '结果状态(success/fail/error)';


--
-- Name: COLUMN pmcp_audit_log.risk_level; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.risk_level IS '风险等级(LOW/MEDIUM/HIGH/CRITICAL)';


--
-- Name: COLUMN pmcp_audit_log.error_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.error_code IS '错误码';


--
-- Name: COLUMN pmcp_audit_log.error_message; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.error_message IS '错误信息';


--
-- Name: COLUMN pmcp_audit_log.start_time; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.start_time IS '开始时间';


--
-- Name: COLUMN pmcp_audit_log.end_time; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.end_time IS '结束时间';


--
-- Name: COLUMN pmcp_audit_log.duration_ms; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.duration_ms IS '耗时毫秒';


--
-- Name: COLUMN pmcp_audit_log.extra_data; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_audit_log.extra_data IS '扩展数据(JSONB)';


--
-- Name: pmcp_audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pmcp_audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pmcp_audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pmcp_audit_log_id_seq OWNED BY public.pmcp_audit_log.id;


--
-- Name: pmcp_crypto_operation_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmcp_crypto_operation_log (
    operator character varying(64),
    operation_type character varying(32),
    datasource_code character varying(64),
    algorithm character varying(32),
    result_status character varying(32),
    error_message text,
    id bigint NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    inserted_by character varying(64),
    updated_by character varying(64)
);


--
-- Name: TABLE pmcp_crypto_operation_log; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.pmcp_crypto_operation_log IS '加解密操作日志';


--
-- Name: COLUMN pmcp_crypto_operation_log.operator; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_crypto_operation_log.operator IS '操作人';


--
-- Name: COLUMN pmcp_crypto_operation_log.operation_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_crypto_operation_log.operation_type IS '操作类型(encrypt/decrypt)';


--
-- Name: COLUMN pmcp_crypto_operation_log.datasource_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_crypto_operation_log.datasource_code IS '关联数据源编码';


--
-- Name: COLUMN pmcp_crypto_operation_log.algorithm; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_crypto_operation_log.algorithm IS '算法(AES-256-GCM/AES-256-CBC)';


--
-- Name: COLUMN pmcp_crypto_operation_log.result_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_crypto_operation_log.result_status IS '结果状态';


--
-- Name: COLUMN pmcp_crypto_operation_log.error_message; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_crypto_operation_log.error_message IS '错误信息';


--
-- Name: pmcp_crypto_operation_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pmcp_crypto_operation_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pmcp_crypto_operation_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pmcp_crypto_operation_log_id_seq OWNED BY public.pmcp_crypto_operation_log.id;


--
-- Name: pmcp_datasource; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmcp_datasource (
    datasource_code character varying(64) NOT NULL,
    datasource_name character varying(128) NOT NULL,
    db_type character varying(32) NOT NULL,
    host character varying(256) NOT NULL,
    port smallint NOT NULL,
    instance_name character varying(128),
    username character varying(128) NOT NULL,
    encrypted_password character varying(512),
    env_code character varying(32) NOT NULL,
    status smallint DEFAULT '1'::smallint NOT NULL,
    connection_string character varying(512),
    max_concurrent smallint DEFAULT '5'::smallint NOT NULL,
    query_timeout smallint DEFAULT '300'::smallint NOT NULL,
    extra_config jsonb,
    id bigint NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    inserted_by character varying(64),
    updated_by character varying(64)
);


--
-- Name: TABLE pmcp_datasource; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.pmcp_datasource IS '数据源配置';


--
-- Name: COLUMN pmcp_datasource.datasource_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource.datasource_code IS '数据源编码';


--
-- Name: COLUMN pmcp_datasource.datasource_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource.datasource_name IS '数据源名称';


--
-- Name: COLUMN pmcp_datasource.db_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource.db_type IS '数据库类型(oracle/mysql)';


--
-- Name: COLUMN pmcp_datasource.instance_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource.instance_name IS '实例名/SID';


--
-- Name: COLUMN pmcp_datasource.username; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource.username IS '连接用户名';


--
-- Name: COLUMN pmcp_datasource.encrypted_password; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource.encrypted_password IS 'AES密文密码';


--
-- Name: COLUMN pmcp_datasource.env_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource.env_code IS '环境标识(DEV/TEST/PROD)';


--
-- Name: COLUMN pmcp_datasource.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource.status IS '1-启用 0-禁用';


--
-- Name: COLUMN pmcp_datasource.connection_string; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource.connection_string IS '完整连接串';


--
-- Name: COLUMN pmcp_datasource.max_concurrent; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource.max_concurrent IS '最大并发数';


--
-- Name: COLUMN pmcp_datasource.query_timeout; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource.query_timeout IS '查询超时(秒)';


--
-- Name: COLUMN pmcp_datasource.extra_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource.extra_config IS '扩展配置';


--
-- Name: pmcp_datasource_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pmcp_datasource_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pmcp_datasource_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pmcp_datasource_id_seq OWNED BY public.pmcp_datasource.id;


--
-- Name: pmcp_datasource_permission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmcp_datasource_permission (
    datasource_id bigint NOT NULL,
    user_id bigint,
    role_id bigint,
    permission_type character varying(32) NOT NULL,
    id bigint NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    inserted_by character varying(64),
    updated_by character varying(64)
);


--
-- Name: TABLE pmcp_datasource_permission; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.pmcp_datasource_permission IS '数据源权限关系';


--
-- Name: COLUMN pmcp_datasource_permission.user_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource_permission.user_id IS '授权用户';


--
-- Name: COLUMN pmcp_datasource_permission.role_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource_permission.role_id IS '授权角色';


--
-- Name: COLUMN pmcp_datasource_permission.permission_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_datasource_permission.permission_type IS '权限类型(query/manage)';


--
-- Name: pmcp_datasource_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pmcp_datasource_permission_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pmcp_datasource_permission_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pmcp_datasource_permission_id_seq OWNED BY public.pmcp_datasource_permission.id;


--
-- Name: pmcp_mcp_call_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmcp_mcp_call_log (
    trace_id character varying(64),
    tool_name character varying(64),
    caller character varying(128),
    datasource_code character varying(64),
    env_code character varying(32),
    input_summary text,
    output_summary text,
    result_status character varying(32),
    error_code character varying(32),
    error_message text,
    duration_ms bigint,
    confirm_token character varying(128),
    extra_data jsonb,
    id bigint NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    inserted_by character varying(64),
    updated_by character varying(64)
);


--
-- Name: TABLE pmcp_mcp_call_log; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.pmcp_mcp_call_log IS 'MCP 调用日志';


--
-- Name: COLUMN pmcp_mcp_call_log.trace_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_mcp_call_log.trace_id IS '全链路追踪标识';


--
-- Name: COLUMN pmcp_mcp_call_log.tool_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_mcp_call_log.tool_name IS 'Tool 名称';


--
-- Name: COLUMN pmcp_mcp_call_log.caller; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_mcp_call_log.caller IS '调用方(Claude Code)';


--
-- Name: COLUMN pmcp_mcp_call_log.datasource_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_mcp_call_log.datasource_code IS '数据源编码';


--
-- Name: COLUMN pmcp_mcp_call_log.env_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_mcp_call_log.env_code IS '环境标识';


--
-- Name: COLUMN pmcp_mcp_call_log.input_summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_mcp_call_log.input_summary IS '输入摘要';


--
-- Name: COLUMN pmcp_mcp_call_log.output_summary; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_mcp_call_log.output_summary IS '输出摘要';


--
-- Name: COLUMN pmcp_mcp_call_log.result_status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_mcp_call_log.result_status IS '结果状态';


--
-- Name: COLUMN pmcp_mcp_call_log.error_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_mcp_call_log.error_code IS '错误码';


--
-- Name: COLUMN pmcp_mcp_call_log.error_message; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_mcp_call_log.error_message IS '错误信息';


--
-- Name: COLUMN pmcp_mcp_call_log.duration_ms; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_mcp_call_log.duration_ms IS '耗时毫秒';


--
-- Name: COLUMN pmcp_mcp_call_log.confirm_token; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_mcp_call_log.confirm_token IS '确认令牌';


--
-- Name: COLUMN pmcp_mcp_call_log.extra_data; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_mcp_call_log.extra_data IS '扩展数据';


--
-- Name: pmcp_mcp_call_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pmcp_mcp_call_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pmcp_mcp_call_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pmcp_mcp_call_log_id_seq OWNED BY public.pmcp_mcp_call_log.id;


--
-- Name: pmcp_permission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmcp_permission (
    permission_name character varying(128) NOT NULL,
    permission_code character varying(128) NOT NULL,
    resource_type character varying(64),
    resource_path character varying(256),
    parent_id bigint,
    status smallint DEFAULT '1'::smallint NOT NULL,
    sort_order smallint DEFAULT '0'::smallint,
    id bigint NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    inserted_by character varying(64),
    updated_by character varying(64)
);


--
-- Name: TABLE pmcp_permission; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.pmcp_permission IS '权限定义';


--
-- Name: COLUMN pmcp_permission.permission_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_permission.permission_name IS '权限名称';


--
-- Name: COLUMN pmcp_permission.permission_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_permission.permission_code IS '权限标识';


--
-- Name: COLUMN pmcp_permission.resource_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_permission.resource_type IS '资源类型(menu/button/api)';


--
-- Name: COLUMN pmcp_permission.resource_path; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_permission.resource_path IS '资源路径';


--
-- Name: COLUMN pmcp_permission.parent_id; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_permission.parent_id IS '父权限ID';


--
-- Name: COLUMN pmcp_permission.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_permission.status IS '1-启用 0-禁用';


--
-- Name: COLUMN pmcp_permission.sort_order; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_permission.sort_order IS '排序';


--
-- Name: pmcp_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pmcp_permission_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pmcp_permission_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pmcp_permission_id_seq OWNED BY public.pmcp_permission.id;


--
-- Name: pmcp_role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmcp_role (
    role_name character varying(64) NOT NULL,
    role_code character varying(64) NOT NULL,
    status smallint DEFAULT '1'::smallint NOT NULL,
    remark character varying(512),
    id bigint NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    inserted_by character varying(64),
    updated_by character varying(64)
);


--
-- Name: TABLE pmcp_role; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.pmcp_role IS '角色信息';


--
-- Name: COLUMN pmcp_role.role_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_role.role_name IS '角色名称';


--
-- Name: COLUMN pmcp_role.role_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_role.role_code IS '角色标识';


--
-- Name: COLUMN pmcp_role.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_role.status IS '1-启用 0-禁用';


--
-- Name: pmcp_role_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pmcp_role_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pmcp_role_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pmcp_role_id_seq OWNED BY public.pmcp_role.id;


--
-- Name: pmcp_role_permission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmcp_role_permission (
    role_id bigint NOT NULL,
    permission_id bigint NOT NULL,
    id bigint NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    inserted_by character varying(64),
    updated_by character varying(64)
);


--
-- Name: TABLE pmcp_role_permission; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.pmcp_role_permission IS '角色权限关系';


--
-- Name: pmcp_role_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pmcp_role_permission_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pmcp_role_permission_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pmcp_role_permission_id_seq OWNED BY public.pmcp_role_permission.id;


--
-- Name: pmcp_skill; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmcp_skill (
    skill_code character varying(64) NOT NULL,
    skill_name character varying(128) NOT NULL,
    description text,
    status smallint DEFAULT '1'::smallint NOT NULL,
    register_method character varying(32),
    tool_count smallint DEFAULT '0'::smallint NOT NULL,
    id bigint NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    inserted_by character varying(64),
    updated_by character varying(64)
);


--
-- Name: TABLE pmcp_skill; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.pmcp_skill IS 'Skill 注册信息';


--
-- Name: COLUMN pmcp_skill.skill_code; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_skill.skill_code IS 'Skill 编码';


--
-- Name: COLUMN pmcp_skill.skill_name; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_skill.skill_name IS 'Skill 名称';


--
-- Name: COLUMN pmcp_skill.description; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_skill.description IS 'Skill 描述';


--
-- Name: COLUMN pmcp_skill.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_skill.status IS '状态 1-启用 0-禁用';


--
-- Name: COLUMN pmcp_skill.register_method; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_skill.register_method IS '注册方式(decorator/form/upload)';


--
-- Name: COLUMN pmcp_skill.tool_count; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_skill.tool_count IS 'Tool 数量';


--
-- Name: pmcp_skill_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pmcp_skill_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pmcp_skill_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pmcp_skill_id_seq OWNED BY public.pmcp_skill.id;


--
-- Name: pmcp_system_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmcp_system_config (
    config_key character varying(128) NOT NULL,
    config_value text,
    config_type character varying(32),
    description character varying(512),
    status smallint DEFAULT '1'::smallint NOT NULL,
    id bigint NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    inserted_by character varying(64),
    updated_by character varying(64)
);


--
-- Name: TABLE pmcp_system_config; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.pmcp_system_config IS '系统参数配置';


--
-- Name: COLUMN pmcp_system_config.config_key; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_system_config.config_key IS '配置键';


--
-- Name: COLUMN pmcp_system_config.config_value; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_system_config.config_value IS '配置值';


--
-- Name: COLUMN pmcp_system_config.config_type; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_system_config.config_type IS '值类型(string/int/json/bool)';


--
-- Name: COLUMN pmcp_system_config.description; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_system_config.description IS '配置说明';


--
-- Name: COLUMN pmcp_system_config.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_system_config.status IS '1-启用 0-禁用';


--
-- Name: pmcp_system_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pmcp_system_config_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pmcp_system_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pmcp_system_config_id_seq OWNED BY public.pmcp_system_config.id;


--
-- Name: pmcp_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmcp_user (
    username character varying(64) NOT NULL,
    password character varying(128) NOT NULL,
    nickname character varying(64),
    status smallint DEFAULT '1'::smallint NOT NULL,
    remark character varying(512),
    id bigint NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    inserted_by character varying(64),
    updated_by character varying(64)
);


--
-- Name: TABLE pmcp_user; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.pmcp_user IS '用户信息';


--
-- Name: COLUMN pmcp_user.status; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON COLUMN public.pmcp_user.status IS '1-启用 0-禁用';


--
-- Name: pmcp_user_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pmcp_user_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pmcp_user_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pmcp_user_id_seq OWNED BY public.pmcp_user.id;


--
-- Name: pmcp_user_role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.pmcp_user_role (
    user_id bigint NOT NULL,
    role_id bigint NOT NULL,
    id bigint NOT NULL,
    inserted_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    inserted_by character varying(64),
    updated_by character varying(64)
);


--
-- Name: TABLE pmcp_user_role; Type: COMMENT; Schema: public; Owner: -
--

COMMENT ON TABLE public.pmcp_user_role IS '用户角色关系';


--
-- Name: pmcp_user_role_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.pmcp_user_role_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: pmcp_user_role_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.pmcp_user_role_id_seq OWNED BY public.pmcp_user_role.id;


--
-- Name: pmcp_audit_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_audit_log ALTER COLUMN id SET DEFAULT nextval('public.pmcp_audit_log_id_seq'::regclass);


--
-- Name: pmcp_crypto_operation_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_crypto_operation_log ALTER COLUMN id SET DEFAULT nextval('public.pmcp_crypto_operation_log_id_seq'::regclass);


--
-- Name: pmcp_datasource id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_datasource ALTER COLUMN id SET DEFAULT nextval('public.pmcp_datasource_id_seq'::regclass);


--
-- Name: pmcp_datasource_permission id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_datasource_permission ALTER COLUMN id SET DEFAULT nextval('public.pmcp_datasource_permission_id_seq'::regclass);


--
-- Name: pmcp_mcp_call_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_mcp_call_log ALTER COLUMN id SET DEFAULT nextval('public.pmcp_mcp_call_log_id_seq'::regclass);


--
-- Name: pmcp_permission id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_permission ALTER COLUMN id SET DEFAULT nextval('public.pmcp_permission_id_seq'::regclass);


--
-- Name: pmcp_role id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_role ALTER COLUMN id SET DEFAULT nextval('public.pmcp_role_id_seq'::regclass);


--
-- Name: pmcp_role_permission id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_role_permission ALTER COLUMN id SET DEFAULT nextval('public.pmcp_role_permission_id_seq'::regclass);


--
-- Name: pmcp_skill id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_skill ALTER COLUMN id SET DEFAULT nextval('public.pmcp_skill_id_seq'::regclass);


--
-- Name: pmcp_system_config id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_system_config ALTER COLUMN id SET DEFAULT nextval('public.pmcp_system_config_id_seq'::regclass);


--
-- Name: pmcp_user id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_user ALTER COLUMN id SET DEFAULT nextval('public.pmcp_user_id_seq'::regclass);


--
-- Name: pmcp_user_role id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_user_role ALTER COLUMN id SET DEFAULT nextval('public.pmcp_user_role_id_seq'::regclass);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: pmcp_audit_log pmcp_audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_audit_log
    ADD CONSTRAINT pmcp_audit_log_pkey PRIMARY KEY (id);


--
-- Name: pmcp_crypto_operation_log pmcp_crypto_operation_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_crypto_operation_log
    ADD CONSTRAINT pmcp_crypto_operation_log_pkey PRIMARY KEY (id);


--
-- Name: pmcp_datasource pmcp_datasource_datasource_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_datasource
    ADD CONSTRAINT pmcp_datasource_datasource_code_key UNIQUE (datasource_code);


--
-- Name: pmcp_datasource_permission pmcp_datasource_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_datasource_permission
    ADD CONSTRAINT pmcp_datasource_permission_pkey PRIMARY KEY (id);


--
-- Name: pmcp_datasource pmcp_datasource_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_datasource
    ADD CONSTRAINT pmcp_datasource_pkey PRIMARY KEY (id);


--
-- Name: pmcp_mcp_call_log pmcp_mcp_call_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_mcp_call_log
    ADD CONSTRAINT pmcp_mcp_call_log_pkey PRIMARY KEY (id);


--
-- Name: pmcp_permission pmcp_permission_permission_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_permission
    ADD CONSTRAINT pmcp_permission_permission_code_key UNIQUE (permission_code);


--
-- Name: pmcp_permission pmcp_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_permission
    ADD CONSTRAINT pmcp_permission_pkey PRIMARY KEY (id);


--
-- Name: pmcp_role_permission pmcp_role_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_role_permission
    ADD CONSTRAINT pmcp_role_permission_pkey PRIMARY KEY (id);


--
-- Name: pmcp_role pmcp_role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_role
    ADD CONSTRAINT pmcp_role_pkey PRIMARY KEY (id);


--
-- Name: pmcp_role pmcp_role_role_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_role
    ADD CONSTRAINT pmcp_role_role_code_key UNIQUE (role_code);


--
-- Name: pmcp_skill pmcp_skill_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_skill
    ADD CONSTRAINT pmcp_skill_pkey PRIMARY KEY (id);


--
-- Name: pmcp_skill pmcp_skill_skill_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_skill
    ADD CONSTRAINT pmcp_skill_skill_code_key UNIQUE (skill_code);


--
-- Name: pmcp_system_config pmcp_system_config_config_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_system_config
    ADD CONSTRAINT pmcp_system_config_config_key_key UNIQUE (config_key);


--
-- Name: pmcp_system_config pmcp_system_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_system_config
    ADD CONSTRAINT pmcp_system_config_pkey PRIMARY KEY (id);


--
-- Name: pmcp_user pmcp_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_user
    ADD CONSTRAINT pmcp_user_pkey PRIMARY KEY (id);


--
-- Name: pmcp_user_role pmcp_user_role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_user_role
    ADD CONSTRAINT pmcp_user_role_pkey PRIMARY KEY (id);


--
-- Name: pmcp_user pmcp_user_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_user
    ADD CONSTRAINT pmcp_user_username_key UNIQUE (username);


--
-- Name: pmcp_datasource_permission pmcp_datasource_permission_datasource_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_datasource_permission
    ADD CONSTRAINT pmcp_datasource_permission_datasource_id_fkey FOREIGN KEY (datasource_id) REFERENCES public.pmcp_datasource(id);


--
-- Name: pmcp_datasource_permission pmcp_datasource_permission_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_datasource_permission
    ADD CONSTRAINT pmcp_datasource_permission_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.pmcp_role(id);


--
-- Name: pmcp_datasource_permission pmcp_datasource_permission_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_datasource_permission
    ADD CONSTRAINT pmcp_datasource_permission_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.pmcp_user(id);


--
-- Name: pmcp_role_permission pmcp_role_permission_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_role_permission
    ADD CONSTRAINT pmcp_role_permission_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.pmcp_permission(id);


--
-- Name: pmcp_role_permission pmcp_role_permission_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_role_permission
    ADD CONSTRAINT pmcp_role_permission_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.pmcp_role(id);


--
-- Name: pmcp_user_role pmcp_user_role_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_user_role
    ADD CONSTRAINT pmcp_user_role_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.pmcp_role(id);


--
-- Name: pmcp_user_role pmcp_user_role_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.pmcp_user_role
    ADD CONSTRAINT pmcp_user_role_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.pmcp_user(id);


--
-- PostgreSQL database dump complete
--

