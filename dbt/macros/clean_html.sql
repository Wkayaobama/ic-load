{% macro clean_html(column_name) %}
    regexp_replace(
        regexp_replace({{ column_name }}, '<[^>]+>', '', 'g'),
        '&[a-zA-Z]+;', '', 'g'
    )
{% endmacro %}
