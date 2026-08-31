{{/*
Shared names, labels and the one piece of logic worth having in a single place.
*/}}

{{- define "mlops-platform.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "mlops-platform.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/*
Labels every object carries. `app.kubernetes.io/version` is quoted because appVersion is `2.22.4`,
which a label value must be a string to hold.
*/}}
{{- define "mlops-platform.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
app.kubernetes.io/name: {{ include "mlops-platform.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/part-of: mlops-platform
{{- end -}}

{{/*
The selector for one component. Deliberately narrow: a selector is immutable on a Deployment, so
anything that can change between releases -- the chart version, the app version -- must not be in it.
Putting `helm.sh/chart` in a selector is the classic way to make the next `helm upgrade` fail.
*/}}
{{- define "mlops-platform.selectorLabels" -}}
app.kubernetes.io/name: {{ include "mlops-platform.name" .root }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/*
An image reference, with the digest when there is one.

This is the only place the digest-or-not decision is made, and it exists because one of the three
images has no digest to pin and cannot have one. `mlops-platform/mlflow` is built locally, so no
registry has ever handed it over and there is nothing to pin to -- record 018 argues that at length.
The other two are pulled and are pinned by tag and digest both.

Called with a values fragment: {{ include "mlops-platform.image" .Values.mlflow.image }}
*/}}
{{- define "mlops-platform.image" -}}
{{- if .digest -}}
{{- printf "%s:%s@%s" .repository .tag .digest -}}
{{- else -}}
{{- printf "%s:%s" .repository .tag -}}
{{- end -}}
{{- end -}}

{{/*
The environment every workload that talks to Postgres or MinIO needs, read from the Secret that
`make kind-deploy` creates from `.env`.

Never a literal, never a default. A `secretKeyRef` means the value reaches the container's
environment and appears nowhere in the rendered manifest, so `kubectl get deploy -o yaml` shows the
key's name and not its value.
*/}}
{{- define "mlops-platform.postgresEnv" -}}
- name: POSTGRES_USER
  valueFrom:
    secretKeyRef:
      name: {{ .Values.credentials.secretName }}
      key: {{ .Values.credentials.keys.postgresUser }}
- name: POSTGRES_PASSWORD
  valueFrom:
    secretKeyRef:
      name: {{ .Values.credentials.secretName }}
      key: {{ .Values.credentials.keys.postgresPassword }}
- name: POSTGRES_DB
  valueFrom:
    secretKeyRef:
      name: {{ .Values.credentials.secretName }}
      key: {{ .Values.credentials.keys.postgresDatabase }}
{{- end -}}

{{- define "mlops-platform.minioEnv" -}}
- name: AWS_ACCESS_KEY_ID
  valueFrom:
    secretKeyRef:
      name: {{ .Values.credentials.secretName }}
      key: {{ .Values.credentials.keys.minioRootUser }}
- name: AWS_SECRET_ACCESS_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.credentials.secretName }}
      key: {{ .Values.credentials.keys.minioRootPassword }}
- name: MLFLOW_S3_ENDPOINT_URL
  value: http://{{ include "mlops-platform.fullname" . }}-minio:{{ .Values.minio.service.apiPort }}
{{- end -}}
