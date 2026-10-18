# Problem Statement: AI-Powered Restaurant Recommendation System (Zomato Use Case)

## Overview

Build an AI-powered restaurant recommendation service inspired by Zomato. The system suggests restaurants based on user preferences by combining structured restaurant data with a Large Language Model (LLM).

## Objective

Design and implement an application that:

- Takes user preferences (location, budget, cuisine, minimum rating)
- Uses a real-world dataset of restaurants
- Uses an LLM to generate personalized, human-like recommendations
- Displays clear and useful results to the user

## Dataset

Zomato restaurant recommendation dataset on Hugging Face:
https://huggingface.co/datasets/ManikaSaini/zomato-restaurant-recommendation

## System Workflow

### 1. Data Ingestion

- Load and preprocess the Zomato dataset from Hugging Face.
- Extract relevant fields: restaurant name, location, cuisine, cost, rating, etc.

### 2. User Input

Collect the following preferences:

| Preference | Example |
|---|---|
| Location | Delhi, Bangalore |
| Budget | low, medium, high |
| Cuisine | Italian, Chinese |
| Minimum rating | numeric threshold |
| Additional preferences | family-friendly, quick service |

### 3. Integration Layer

- Filter and prepare relevant restaurant data based on user input.
- Pass the structured results into an LLM prompt.
- Design a prompt that helps the LLM reason about and rank the options.

### 4. Recommendation Engine

Use the LLM to:

- Rank restaurants
- Explain why each recommendation fits the user's preferences
- Optionally summarize the choices

### 5. Output Display

Present the top recommendations in a user-friendly format, each showing:

- Restaurant name
- Cuisine
- Rating
- Estimated cost
- AI-generated explanation
