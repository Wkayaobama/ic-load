{% macro clean_french_utf8(column_name) %}
    replace(
        replace(
            replace(
                replace(
                    replace(
                        replace(
                            replace(
                                replace({{ column_name }}, 'Ã©', 'é'),
                                'Ã¨', 'è'
                            ),
                            'Ãª', 'ê'
                        ),
                        'Ã ', 'à'
                    ),
                    'Ã¢', 'â'
                ),
                'Ã®', 'î'
            ),
            'Ã´', 'ô'
        ),
        'Ã§', 'ç'
    )
{% endmacro %}
