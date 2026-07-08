# BUILD-039A do-not-repeat note

Repeated Render redeploys were not sufficient after BUILD-039 because the browser still needed CORS access to Mission Control telemetry routes.

Do not continue redeploying the same commit if Mission Control still reports browser load/CORS failures. Merge this hotfix first, then redeploy once.
