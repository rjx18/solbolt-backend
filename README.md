# Solbolt Backend

This repository contains the code for the backend of Solbolt, a compiler explorer and 
gas analysis tool for Solidity.

This backend can be served with docker-compose.

## Running it

Make sure Docker and docker-compose is installed

To start the backend, use:

### `docker compose up`

The docker container will automatically install the necessary dependencies and start the
necessary containers. You may need to edit the certbot container if you do not require SSL.
Also, make sure that the necessary ports are open for access.

To run the evaluation script, use:

### `python3 eval.py`

This will provide more options about how the script can be run.