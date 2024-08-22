import argparse
from abc import ABC, abstractmethod


class _BaseConfig(ABC):

    @abstractmethod
    def configure(self, args: argparse.Namespace) -> None:
        raise NotImplementedError

    @abstractmethod
    def verify(self, args: argparse.Namespace) -> bool:
        raise NotImplementedError
