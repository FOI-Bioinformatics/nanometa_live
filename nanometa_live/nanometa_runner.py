import argparse
import subprocess
import time
import logging
import os
import sys
import signal
import yaml
from nanometa_live.helpers.file_utils import remove_temp_files
from nanometa_live.helpers.config_utils import load_config
from nanometa_live import __version__


def setup_logging():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
    )


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Starting the Nanometa Live pipeline."
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to the configuration file. Default is config.yaml.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show the current version of the script.",
    )
    parser.add_argument(
        "-p", "--path", default="", help="The path to the project directory."
    )
    return parser.parse_args()


def start_processes(commands, args):
    processes = []
    for cmd in commands:
        cmd_with_args = [cmd]

        if args.config:
            cmd_with_args.extend(["--config", args.config])

        if args.path:
            cmd_with_args.extend(["-p", args.path])

        logging.info(f"Starting process: {' '.join(cmd_with_args)}")

        process = subprocess.Popen(
            cmd_with_args
        )  # Note: removed shell=True for better security
        processes.append(process)

    return processes


def terminate_processes(processes, config_contents):
    for process in processes:
        logging.info(f"Terminating processes: {process}")
        process.terminate()
        process.wait()

    # clear temporary files
    if config_contents.get("remove_temp_files") == "yes":
        remove_temp_files(config_contents)
    # /


# define custom trigger and integrate it (this signal is sent from the web-GUI to shut down the software)
def trigger_keyboard_interrupt(signum, frame):
    raise KeyboardInterrupt()


signal.signal(signal.SIGUSR1, trigger_keyboard_interrupt)
# /


def main():
    setup_logging()
    args = parse_arguments()

    # parse config-file (confirm that it exists for downstream scripts)
    config_file_path = ""
    if args.path:
        config_file_path = args.path + "/"
    config_file_path = config_file_path + args.config
    try:
        config_contents = load_config(config_file_path)

        if config_contents is None:
            raise Exception  # if no content parsed, raise error.
    except FileNotFoundError:
        logging.error(
            "Could not locate config-file at specified path! Terminating..."
        )
        sys.exit()
    except yaml.YAMLError:
        logging.error(
            "Config file parsing error. Please make sure that the config-file is properly formatted! Terminating..."
        )
        sys.exit()
    # /

    commands = ["nanometa-backend", "nanometa-gui"]
    try:
        processes = start_processes(commands, args)

        # write ID of main process
        with open(".runtime", "w") as nf:
            nf.write(str(os.getpid()))
        # /

        while True:
            time.sleep(0.1)

    except KeyboardInterrupt:
        terminate_processes(processes, config_contents)

    except Exception as e:
        logging.error(f"Error: {e}")

    finally:
        logging.info("Processes terminated")


if __name__ == "__main__":
    main()
