apiVersion: v1
kind: Config
clusters:
- name: ${cluster_name}
  cluster:
    server: ${cluster_endpoint}
    certificate-authority-data: ${cluster_ca}
contexts:
- name: ${namespace}
  context:
    cluster: ${cluster_name}
    namespace: ${namespace}
    user: ${namespace}-sa
current-context: ${namespace}
users:
- name: ${namespace}-sa
  user:
    token: ${token}
