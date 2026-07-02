PROJECT
===================================

<workstation>
{{#list environment prefix="- " join="\n"}}{{label}}: {{value}}{{/list}}
{{#if model}}- Model: {{model}}{{/if}}
</workstation>

{{#if contextFiles.length}}
<context>
Follow these context files:
{{#each contextFiles}}
<file path="{{path}}">
{{content}}
</file>
{{/each}}
</context>
{{/if}}

{{#if agentsMdSearch.files.length}}
<dir-context>
Deeper directory rules override higher ones. Before changing files there, read:
{{#list agentsMdSearch.files join="\n"}}- {{this}}{{/list}}
</dir-context>
{{/if}}

{{#ifAny contextFiles.length agentsMdSearch.files.length}}
The context above is already loaded; do not search for more agent/context files unless a listed rule says to.
{{/ifAny}}

Today is {{date}}, and the current working directory is '{{#if workspaceTree.rootPath}}{{workspaceTree.rootPath}}{{else}}{{cwd}}{{/if}}'.

{{#if appendPrompt}}
{{appendPrompt}}
{{/if}}
