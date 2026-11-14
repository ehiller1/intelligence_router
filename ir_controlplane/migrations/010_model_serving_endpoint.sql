-- ir_dispatch: the name a model is called by at its deployment_endpoint.
--
-- deployment_endpoint (002) is the server root, e.g. http://10.0.0.5:8000;
-- dispatch appends /v1/chat/completions. served_model_name is the request's
-- `model` field. For a distilled student it is the LoRA adapter's name on a
-- shared vLLM server, which is how several experts share one deployment of
-- their base model. Mirrors ir_core.resolution.ServingEndpoint.
--
-- Nullable: a registered model that is not deployed has no name to be called
-- by, and dispatch skips it. No credential is stored here; ir_dispatch looks
-- credentials up by model_id from its own secret store.

ALTER TABLE ir_model_registry
    ADD COLUMN served_model_name TEXT;

ALTER TABLE ir_model_registry
    ADD COLUMN endpoint_api TEXT NOT NULL DEFAULT 'openai-chat'
        CHECK (endpoint_api IN ('openai-chat'));

COMMENT ON COLUMN ir_model_registry.served_model_name IS
    'Value of the model field in requests to deployment_endpoint (the LoRA adapter name for a distilled student). NULL means not deployed: dispatch never calls it.';
