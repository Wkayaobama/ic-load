-- Classify Comm_Action to HubSpot Activity Type
-- Classification logic based on Comm_Action distribution:
--   Meeting (59,038) -> MEETING
--   EmailOut (11,120) -> NOTE
--   PhoneOut (5,933) -> CALL
--   EmailIn (861) -> NOTE
--   ToDo (145) -> TASK

select
    *,

    -- HubSpot activity type classification
    case comm_action
        when 'Meeting' then 'MEETING'
        when 'EmailOut' then 'NOTE'
        when 'PhoneOut' then 'CALL'
        when 'EmailIn' then 'NOTE'
        when 'ToDo' then 'TASK'
        else 'NOTE'
    end as hubspot_activity_type,

    -- Call direction (only for phone activities)
    case
        when comm_action = 'PhoneOut' then 'OUTBOUND'
        when comm_action = 'PhoneIn' then 'INBOUND'
        else null
    end as call_direction,

    -- Initial status based on activity type
    case comm_action
        when 'Meeting' then 'SCHEDULED'
        when 'ToDo' then 'NOT_STARTED'
        else null
    end as initial_status,

    -- Email direction (for notes from email)
    case
        when comm_action = 'EmailOut' then 'OUTBOUND'
        when comm_action = 'EmailIn' then 'INBOUND'
        else null
    end as email_direction

from {{ ref('stg_bronze_communication') }}
