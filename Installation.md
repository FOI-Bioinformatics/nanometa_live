## Installation Guide
This guide explains how to set up Nanometa Live on your computer. For the smoothest installation, we suggest using [Mambaforge](https://github.com/conda-forge/miniforge#mambaforge).

### Option 1: Install with Conda/Mamba (Recommended)

1. **Create a New Environment:**

    To install Nanometa Live, first make a new environment in either Conda or Mamba. Run the following command in your terminal:

    ```bash
    mamba create --name nanometa_live_env nanometa-live
    ```
    This command creates an isolated space ('nanometa_live_env') for running Nanometa Live.

2. **Activate the Environment:**

    Once the environment is ready, you need to switch to it. Do this with the following command:

    ```bash
    mamba activate nanometa_live_env
    ```

    You'll know you're in the right environment when you see 'nanometa_live_env' in your command prompt.

### Option 2: Install with Docker

Using Docker, you can run Nanometa Live in a container, which is a great way to ensure it works consistently across different computers.

1. **Install Docker:**

   If Docker is not already installed on your system, download and install it from the [official Docker website](https://www.docker.com/get-started). Follow the installation instructions for your specific operating system.

2. **Pull the Nanometa Live Docker image:**

   To get the Nanometa Live image, use this command:

   ```bash
   docker pull quay.io/biocontainers/nanometa-live:0.4.2--pyhdfd78af_0
   ```

   This downloads the specific Nanometa Live image for Docker. Make sure to download the latest version. 

3. **Start Nanometa Live in a Docker container:**

   Start an interactive session in Docker container using:

   ```bash
   DATADIR=/path/to/host/data
   
   docker run -it -v $DATADIR:$DATADIR -p 8050:8050 quay.io/biocontainers/nanometa-live:0.4.2--pyhdfd78af_0 /bin/bash
   ```

   Replace /path/to/host/data with your data folder path. The -v flag links your local data folder to the Docker container. The -p flag allows you to use Nanometa Live's web interface from your browser.

   After starting the Docker container, check if Nanometa Live is running:

   ```
   nanometa-live --version
   ```

4. **Learn More About Docker:**

   FFor advanced Docker features, like setting environment variables or running in detached mode, see the [Docker documentation](https://docs.docker.com).



### Option 3: Install with Singularity

Nanometa Live can also be used through Singularity, a program that allows you to create and use containers. This method is especially useful if you can't or don't want to use Docker. It's a great choice for those who prefer using ready-made containers from Biocontainers.

1. **Check if Singularity is Installed:**

   First, make sure you have Singularity on your computer. You can check by typing this command:

   ```bash
   singularity --version
   ```

   If Singularity is not installed, follow the installation guide on the [official Singularity website](https://sylabs.io/guides/3.0/user-guide/installation.html).

2. **Pull Nanometa Live Container:**

   Get the Nanometa Live container from Biocontainers using this command:

   ```bash
   DATADIR=/path/to/host/data
   
   singularity  shell --nohttps --bind $DATADIR:$DATADIR docker://quay.io/biocontainers/nanometa-live:0.4.2--pyhdfd78af_0
   ```

   Replace /path/to/host/data with the path to your data. This command downloads the container with Nanometa Live.

3. **Start Nanometa Live in Singularity:**

   Once you have the container, you can start Nanometa Live by running:

   ```bash
   nanometa-live --version
   ```

   This command opens Nanometa Live inside the Singularity container.

4. **Learn More About Singularity:**

   If you want to customize how you use Singularity, check out the [Singularity user guide](https://sylabs.io/guides/3.0/user-guide/).

### Option 4: Install from source code

1. **Get the Source Code:**

    Start by downloading the Nanometa Live code from GitHub:

    ```bash
    git clone https://github.com/FOI-Bioinformatics/nanometa_live
    ```
    This command copies the entire Nanometa Live project to your computer.

2. **Go to the Project Folder:**

    Next, change to the directory where you downloaded the project. It should have a file called `nanometa_live_env.yml`.

    ```bash
    cd nanometa_live
    ```
   
4. **Set Up the Environment:**

    Run the following command to create a new environment based on the `nanometa_live_env.yml` file:

    ```bash
    mamba env create -f nanometa_live_env.yml
    ```

5. **Activate the Environment:**

    Activate the newly created environment:

    ```bash
    mamba activate nanometa_live_env
    ```
    You're now working in the environment specifically configured for Nanometa Live.

6. **Install the Program:**

    While in the directory that contains the `setup.py` file, execute the following command to install the program:

    ```bash
    pip install .
    ```
    This command installs Nanometa Live on your system.
