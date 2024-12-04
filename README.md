# Letterboxd Followers

![Build Status](https://img.shields.io/badge/build-passing-brightgreen)

## Description
This project automates the process of following users on Letterboxd, a social networking service for film enthusiasts. It utilizes browser automation to interact with the Letterboxd platform and logs the followed users into a CSV file. The motivation behind this project is to simplify the process of building a network on Letterboxd by automating repetitive tasks, thus allowing users to focus on discovering and sharing films.

## Features
- **Automated Login**: Securely logs into Letterboxd using environment variables for credentials.
- **User Following**: Automatically follows users based on predefined criteria, such as shared film interests.
- **CSV Logging**: Records details of followed users in a CSV file for easy tracking and analysis.
- **Configurable Settings**: Uses a configuration file to adjust parameters like follow limits and time intervals.
- **Error Handling**: Implements robust error handling to ensure smooth operation and logging of issues.

## Requirements
- **Python 3.x**: Ensure Python is installed on your system.
- **Dependencies**: Install using `requirements.txt`. Key libraries include:
  - `playwright`: For browser automation.
  - `dotenv`: To manage environment variables.
  - `agentql`: For querying elements on web pages.

## Installation
1. **Clone the Repository**
   ```bash
   git clone https://github.com/yourusername/letterboxd-followers.git
   cd letterboxd-followers
   ```
2. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```
3. **Environment Setup**
   - Create a `.env` file for environment variables (refer to `parameters.py.example` for guidance).
   - Configure the `parameters.py` file to set up necessary parameters.

## Usage
- **Running the Script**
  ```bash
  python follow.py
  ```
- **Logs and Outputs**
  - Check `letterboxd_follower.log` for detailed logs.
  - Review `connections.csv` for a list of followed users.

## Contributing
- Fork the repository and create a new branch for your feature or bug fix.
- Follow the existing code style and add tests for any new functionality.
- Submit a pull request with a clear description of your changes.

## License
This project is licensed under the terms specified in the `LICENSE` file.

## Contact
For support or inquiries, please contact [your-email@example.com](mailto:your-email@example.com).

## Acknowledgments
- Special thanks to the contributors of the libraries used in this project.
- Inspired by the community of film enthusiasts on Letterboxd.
