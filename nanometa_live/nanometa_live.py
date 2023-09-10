import argparse
import subprocess
import time
import logging
from nanometa_live import __version__  # Import the version number

def setup_logging():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def parse_arguments():
    parser = argparse.ArgumentParser(description='Starting the Nanometa Live pipeline.')
    parser.add_argument('--config', default='config.yaml',
                        help='Path to the configuration file. Default is config.yaml.')
    parser.add_argument('--version', action='version', version=f'%(prog)s {__version__}',
                        help="Show the current version of the script.")
    parser.add_argument('-p', '--path', default='', help="The path to the project directory.")
    return parser.parse_args()

def start_processes(commands, args):
    processes = []
    for cmd in commands:
        cmd_with_args = f"{cmd} --config {args.config} -p {args.path}"
        logging.info(f"Starting process: {cmd_with_args}")
        process = subprocess.Popen(cmd_with_args, shell=True)
        processes.append(process)
    return processes

def terminate_processes(processes):
    for process in processes:
        logging.info(f'Terminating processes: {process}')
        process.terminate()
        process.wait()

def main():
    setup_logging()
    args = parse_arguments()
    commands = ['nanometa-backend', 'nanometa-gui']

    try:
        processes = start_processes(commands, args)

        while True:
            time.sleep(0.1)

    except KeyboardInterrupt:
        terminate_processes(processes)

    except Exception as e:
        logging.error(f'Error: {e}')

    finally:
        logging.info('Processes terminated')

if __name__ == "__main__":
    main()
