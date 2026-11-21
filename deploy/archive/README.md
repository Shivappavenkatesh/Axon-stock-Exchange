# Archived deployment files

These scripts deployed the previous Axon code (`axon_aone`, `run_trader.py`, `run_web.py`,
Streamlit). They do not work with the new `src/axon` package and are kept only for reference.

Azure Container Instances and Kubernetes also cannot keep a fixed outgoing IP as configured
here, which the SEBI static-IP rule for API orders requires. Use the root `docker-compose.yml`
on one VM with a static IP instead (see the main README).
