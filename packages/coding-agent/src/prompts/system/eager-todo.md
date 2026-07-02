<system-reminder>
{{#if forced}}
Before substantive work, create a phased todo. You MUST call `{{toolRefs.todo}}` first with a single `init` op covering investigation, implementation, and verification. The `init` op accepts phase names and task-label strings only. Continue after it succeeds.
{{else}}
Consider calling `{{toolRefs.todo}}` first with a phased `init` plan. The `init` op accepts phase names and task-label strings only. Continue after creating it.
{{/if}}
</system-reminder>
