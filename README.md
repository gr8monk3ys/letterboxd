# Letterboxd Automation Toolkit

A comprehensive toolkit for automating Letterboxd interactions, including user following and review generation.

## Features

- Automated user following with anti-detection measures
- AI-powered movie review generation
- User data scraping and analysis
- Detailed logging and progress tracking

## Project Structure

```
letterboxd-followers/
├── data/                  # Raw data files
├── logs/                  # Log files
├── output/               # Generated output files
├── src/                  # Source code
│   ├── config/          # Configuration files
│   ├── utils/           # Utility functions
│   ├── scraping/        # Scraping related code
│   ├── following/       # Following related code
│   └── reviews/         # Review generation code
```

## Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/letterboxd-followers.git
cd letterboxd-followers
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -e .
```

4. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your API keys
```

## Usage

### User Following
```bash
python -m src.following.follower
```

### Review Generation
```bash
python -m src.reviews.generator
```

### Data Scraping
```bash
python -m src.scraping.scraper
```

## Configuration

- Edit `src/config/config.py` for general settings
- Use `.env` file for sensitive information
- Adjust parameters in each module for specific behavior

## Logging

All logs are stored in the `logs/` directory:
- `follower.log`: Following activity
- `scraper.log`: Scraping activity
- `review_generation.log`: Review generation activity

## Contributing

1. Fork the repository
2. Create your feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Disclaimer

This tool is for educational purposes only. Use responsibly and in accordance with Letterboxd's terms of service.
