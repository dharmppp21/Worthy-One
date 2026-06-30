{{/*
Helm helpers for signforge chart
*/}}

{{/*
Expand the name of the chart.
*/}}
{{- define "signforge.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
We truncate at 63 chars because some Kubernetes name fields are limited to this (by the DNS naming spec).
If release name contains chart name it will be used as a full name.
*/}}
{{- define "signforge.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "signforge.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "signforge.labels" -}}
helm.sh/chart: {{ include "signforge.chart" . }}
{{ include "signforge.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "signforge.selectorLabels" -}}
app.kubernetes.io/name: {{ include "signforge.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Create the name of the service account to use
*/}}
{{- define "signforge.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "signforge.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
PostgreSQL service name
*/}}
{{- define "signforge.postgresql.fullname" -}}
{{- printf "%s-postgresql" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Redis service name
*/}}
{{- define "signforge.redis.fullname" -}}
{{- printf "%s-redis-master" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Kafka service name
*/}}
{{- define "signforge.kafka.fullname" -}}
{{- printf "%s-kafka" .Release.Name | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Database URL
*/}}
{{- define "signforge.databaseUrl" -}}
{{- if .Values.postgresql.enabled }}
{{- printf "postgresql://%s:%s@%s:5432/%s" .Values.postgresql.auth.username .Values.postgresql.auth.password (include "signforge.postgresql.fullname" .) .Values.postgresql.auth.database }}
{{- else }}
{{- .Values.env.DATABASE_URL }}
{{- end }}
{{- end }}

{{/*
Redis URL
*/}}
{{- define "signforge.redisUrl" -}}
{{- if .Values.redis.enabled }}
{{- printf "redis://%s:6379" (include "signforge.redis.fullname" .) }}
{{- else }}
{{- .Values.env.REDIS_URL }}
{{- end }}
{{- end }}

{{/*
Kafka brokers
*/}}
{{- define "signforge.kafkaBrokers" -}}
{{- if .Values.kafka.enabled }}
{{- printf "%s:9092" (include "signforge.kafka.fullname" .) }}
{{- else }}
{{- .Values.env.KAFKA_BROKERS }}
{{- end }}
{{- end }}
