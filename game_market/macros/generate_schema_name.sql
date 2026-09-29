{#- Use the configured schema name as-is (staging, intermediate, marts, seeds) instead of dbt's
    default <target_schema>_<custom_schema> (main_staging, ...). Models without +schema go to the target schema. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
