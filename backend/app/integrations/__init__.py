"""External-system integrations: knowledge-source adapters (plain Markdown,
Obsidian) that adapt third-party document shapes into the provider-neutral
`app.engine.knowledge` types, and provider adapters (`nemotron`) that
implement `app.engine.knowledge`/`app.engine.manager` Protocols against an
external service. Never imported by, and never modifies, the engine layer
itself -- each subpackage implements an existing Protocol from the outside."""
