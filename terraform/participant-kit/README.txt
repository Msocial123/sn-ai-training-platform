ServiceNow AI Training -- Your Lab Environment
================================================

This folder gives you access to YOUR OWN isolated namespace on the shared
training Kubernetes cluster. Nothing you do here affects any other
participant, and nothing they do affects you.

WHAT'S IN THIS FOLDER
  participant-XX.yaml   Your personal cluster credentials. Do not share it --
                        it only works for your own namespace, but treat it
                        like a password.
  connect.sh            Run this on macOS / Linux / WSL / Git Bash.
  connect.ps1           Run this on Windows PowerShell.

STEP 1 -- Install kubectl (if you don't already have it)
  Windows:      winget install -e --id Kubernetes.kubectl
  macOS:        brew install kubectl
  Linux:        see https://kubernetes.io/docs/tasks/tools/

STEP 2 -- Connect
  Windows (PowerShell):
      cd path\to\this\folder
      .\connect.ps1

  macOS / Linux / WSL:
      cd path/to/this/folder
      chmod +x connect.sh
      ./connect.sh

  The script finds your kubeconfig automatically, points kubectl at it, and
  runs a quick connection test. No AWS account or AWS credentials needed --
  your kubeconfig file is all you need.

STEP 3 -- Work in your namespace
  kubectl get all -n participant-XX      (XX = your number)
  kubectl apply -f your-app.yaml -n participant-XX

  Everything you deploy, break, scale, or delete stays inside your own
  namespace -- that's the point. Go ahead and experiment.

TROUBLESHOOTING
  "kubectl: command not found"     -> install kubectl (Step 1)
  "Forbidden" on your own namespace -> contact the trainer, your token may
                                        need to be reissued
  Can't reach the cluster at all    -> check your internet connection; the
                                        cluster's API is public, no VPN needed
