{{- define "aegismem.fullname" -}}{{ .Release.Name }}-aegismem{{- end -}}
{{- define "aegismem.labels" -}}
app.kubernetes.io/name: aegismem
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}
{{- define "aegismem.selector" -}}
app.kubernetes.io/name: aegismem
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: api
{{- end -}}
{{- define "aegismem.image" -}}
{{- if .Values.image.digest -}}{{ .Values.image.repository }}@{{ .Values.image.digest }}
{{- else -}}{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}{{- end -}}
{{- end -}}
{{- define "aegismem.podSecurity" -}}
runAsNonRoot: true
runAsUser: 10001
fsGroup: 10001
seccompProfile: { type: RuntimeDefault }
{{- end -}}
{{- define "aegismem.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities: { drop: ["ALL"] }
{{- end -}}
