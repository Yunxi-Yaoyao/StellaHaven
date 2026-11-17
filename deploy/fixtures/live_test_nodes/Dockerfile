FROM stella-live-fixture-base:70729b46c69b
COPY bundle /fixture
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /fixture
ENTRYPOINT ["python","-u","/fixture/worker.py"]
