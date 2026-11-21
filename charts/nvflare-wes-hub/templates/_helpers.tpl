{{/* Name of all objects of a release, with room for the longest suffix
(`-kits`) within the 63 characters of a name */}}
{{- define "hub.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 58 | trimSuffix "-" -}}
{{- end -}}

{{/* Labels of all objects */}}
{{- define "hub.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{/* Labels that select the pod */}}
{{- define "hub.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* The image, for the hub and for the tasks at the sites */}}
{{- define "hub.image" -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag -}}
{{- end -}}

{{/* The token source of the gateway (`TES_GATEWAY_TOKEN_SOURCE`): a token file
of `tokenSecret`, or `oauth`, never a token */}}
{{- define "hub.gatewayTokenSource" -}}
{{- $gateway := .Values.tesGateway -}}
{{- if and $gateway.tokenFile $gateway.oauth -}}
{{- fail "tesGateway: set tokenFile or oauth, not both" -}}
{{- else if $gateway.tokenFile -}}
{{- if not .Values.tokenSecret -}}
{{- fail "tesGateway.tokenFile is a key of tokenSecret, which is empty" -}}
{{- end -}}
{{- dict "token_file" (printf "/run/secrets/tes-tokens/%s" $gateway.tokenFile) | toJson -}}
{{- else if $gateway.oauth -}}
{{- if not .Values.envSecret -}}
{{- fail "tesGateway.oauth takes its secrets from envSecret, which is empty" -}}
{{- end -}}
{{- dict "oauth" $gateway.oauth | toJson -}}
{{- else -}}
{{- fail "tesGateway.url needs tesGateway.tokenFile or tesGateway.oauth" -}}
{{- end -}}
{{- end -}}
