## Installation Guide
This section provides detailed instructions on how to install Nanometa Live. We recommend using [Mambaforge](https://github.com/conda-forge/miniforge#mambaforge) for a seamless installation experience.

### Option 1: Install with Conda/Mamba (Recommended)

1. **Create a New Environment:**

    Create a new Conda or Mamba environment and install Nanometa Live. Run the following command in your terminal:

    ```bash
    mamba create --name nanometa_live_env nanometa-live
    ```

2. **Activate the Environment:**

    After the environment is created, activate it using the following command:

    ```bash
    mamba activate nanometa_live_env
    ```

    You should now see the environment name in your command prompt.



### Option 2: Install with Singularity and Biocontainers

Nanometa Live can be operated using Singularity, a container platform ideal for environments where Docker is not available or preferred. This approach is suitable for users interested in leveraging Biocontainers for a ready-to-use Singularity container.

1. **Verify Singularity Installation:**

   Ensure Singularity is installed on your system. Verify its presence by running:

   ```bash
   singularity --version
   ```

   If Singularity is not installed, follow the installation guide on the [official Singularity website](https://sylabs.io/guides/3.0/user-guide/installation.html).

2. **Pull Nanometa Live Container:**

   Obtain the Nanometa Live container from Biocontainers with this command:

   ```bash
   singularity pull nanometa-live.sif docker://quay.io/biocontainers/nanometa-live:latest
   ```

   This command downloads the Singularity Image File (SIF) with Nanometa Live.

3. **Run Nanometa Live Using Singularity:**

   After downloading the container, start Nanometa Live with:

   ```bash
   singularity run nanometa-live.sif
   ```

   This will launch Nanometa Live within the Singularity container.

4. **Access Host System Data:**

   To use data from your host system inside the container, mount host directories using the `--bind` option:

   ```bash
   singularity run --bind /path/to/host/data:/data nanometa-live.sif
   ```

   Replace `/path/to/host/data` with your host system's data directory path.

5. **Explore Additional Commands:**

   For further customization and control in Singularity, refer to the [Singularity user guide](https://sylabs.io/guides/3.0/user-guide/).

With this setup, Nanometa Live can be efficiently run in a containerized environment, ensuring reproducibility and ease of use across various computational platforms.


Certainly! Here is an additional installation option for running Nanometa Live using Docker:


### Option 3: Install with Docker

Docker provides a convenient and consistent platform for running software in containers, making it an excellent choice for deploying Nanometa Live in a variety of environments.

1. **Install Docker:**

   If Docker is not already installed on your system, download and install it from the [official Docker website](https://www.docker.com/get-started). Follow the installation instructions for your specific operating system.

2. **Pull the Nanometa Live Docker Image:**

   Pull the official Nanometa Live image from Docker Hub using this command:

   ```bash
   docker pull nanometa/nanometa-live:latest
   ```

   This command downloads the latest version of the Nanometa Live Docker image.

3. **Run Nanometa Live in a Docker Container:**

   Start Nanometa Live within a Docker container using:

   ```bash
   docker run -p 8080:8080 nanometa/nanometa-live:latest
   ```

   The `-p` flag maps a port from your host machine to the container, allowing you to access the Nanometa Live GUI via a web browser.

4. **Access the Web Interface:**

   Open a web browser and navigate to `http://localhost:8080` to access the Nanometa Live GUI. This interface will be served from the Docker container.

5. **Data Volume Mounting (Optional):**

   If you wish to process data stored on your host machine, mount the data directory as a volume in the Docker container:

   ```bash
   docker run -p 8080:8080 -v /path/to/host/data:/data nanometa/nanometa-live:latest
   ```

   Replace `/path/to/host/data` with the path to your data directory. This step ensures that the Docker container has access to your local data.

6. **Additional Docker Commands:**

   For more advanced Docker usage, such as setting environment variables or running in detached mode, consult the [Docker documentation](https://docs.docker.com).

With Docker, you can rapidly deploy Nanometa Live across different systems with minimal setup, ensuring consistent performance and behavior regardless of the underlying host environment.


### Option 4: Install from Source Code

1. **Clone the Repository:**

    First, clone the Nanometa Live repository from GitHub to your local machine:

    ```bash
    git clone https://github.com/FOI-Bioinformatics/nanometa_live
    ```

2. **Navigate to the Project Directory:**

    Move to the directory where the cloned repository is located. The directory should contain a file named `nanometa_live_env.yml`.

3. **Create the Environment from the YML File:**

    Run the following command to create a new environment based on the `nanometa_live_env.yml` file:

    ```bash
    mamba env create -f nanometa_live_env.yml
    ```

4. **Activate the Environment:**

    Activate the newly created environment:

    ```bash
    mamba activate nanometa_live_env
    ```

5. **Install the Program:**

    While in the directory that contains the `setup.py` file, execute the following command to install the program:

    ```bash
    pip install .
    ```