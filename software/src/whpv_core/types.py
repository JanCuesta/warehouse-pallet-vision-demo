from dataclasses import dataclass


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    bbox_xyxy: tuple[float, float, float, float]


@dataclass(frozen=True)
class OrderRequirement:
    driver: str
    client: str
    product: str
    required_quantity: int
    completed_quantity: int = 0
    order_id: str | None = None

    def __post_init__(self):
        if (
            type(self.required_quantity) is not int
            or self.required_quantity <= 0
        ):
            raise ValueError("Required quantity must be a positive integer")

        if (
            type(self.completed_quantity) is not int
            or not 0 <= self.completed_quantity <= self.required_quantity
        ):
            raise ValueError("Invalid completed quantity")

    @property
    def remaining_quantity(self) -> int:
        return self.required_quantity - self.completed_quantity
