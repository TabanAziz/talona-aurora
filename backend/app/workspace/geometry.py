"""Validate drawing data before either viewer receives it."""
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Shape(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Wall(Shape):
    id: str = Field(min_length=1, max_length=100)
    level: str | None = None
    x1: float
    y1: float
    x2: float
    y2: float
    thickness: float = Field(gt=0, le=2000)
    kind: Literal["exterior", "interior", "partition"] = "partition"


class Opening(Shape):
    wall: str
    offset: float = Field(ge=0)
    width: float = Field(gt=0)
    kind: Literal["door", "window"]


class Room(Shape):
    label: str = Field(min_length=1, max_length=100)
    level: str | None = None
    x: float
    y: float


class Geometry(Shape):
    sheet: str
    level: str | None = None
    revision: str
    units: Literal["mm"] = "mm"
    width: float = Field(gt=0, le=1000000)
    height: float = Field(gt=0, le=1000000)
    wall_height: float = Field(default=2700, gt=0, le=100000)
    walls: list[Wall] = Field(default_factory=list, max_length=2000)
    openings: list[Opening] = Field(default_factory=list, max_length=4000)
    rooms: list[Room] = Field(default_factory=list, max_length=1000)
    changed: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_coordinates(self):
        ids = {wall.id for wall in self.walls}
        if len(ids) != len(self.walls):
            raise ValueError("Wall ids must be unique")
        for wall in self.walls:
            if wall.x1 == wall.x2 and wall.y1 == wall.y2:
                raise ValueError("A wall must have length")
            for x, y in ((wall.x1, wall.y1), (wall.x2, wall.y2)):
                if not (0 <= x <= self.width and 0 <= y <= self.height):
                    raise ValueError("Wall coordinates must be inside the sheet")
        for room in self.rooms:
            if not (0 <= room.x <= self.width and 0 <= room.y <= self.height):
                raise ValueError("Room labels must be inside the sheet")
        walls = {wall.id: wall for wall in self.walls}
        for opening in self.openings:
            wall = walls.get(opening.wall)
            if wall is None or opening.offset + opening.width > math.hypot(wall.x2-wall.x1, wall.y2-wall.y1):
                raise ValueError("An opening must fit its wall")
        if not set(self.changed) <= ids:
            raise ValueError("Changed walls must exist")
        return self
