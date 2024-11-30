FROM python:3.11.9-alpine3.20
WORKDIR /code
EXPOSE 80
COPY . .
RUN pip install -r requirements.txt
CMD ["python", "-m", "app"]