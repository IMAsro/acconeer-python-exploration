from __future__ import annotations

import re
from typing import Callable, Iterable, Tuple, TypeVar

import h5py
import numpy as np

from acconeer.exptool.a121._entities import (
    ClientInfo,
    Metadata,
    PersistentRecord,
    Result,
    ResultContext,
    ServerInfo,
    SessionConfig,
)


T = TypeVar("T")


class H5Record(PersistentRecord):
    file: h5py.File

    def __init__(self, file: h5py.File) -> None:
        self.file = file

    @property
    def client_info(self) -> ClientInfo:
        return ClientInfo.from_json(self.file["client_info"][()])

    @property
    def extended_metadata(self) -> list[dict[int, Metadata]]:
        return self._map_over_entries(self._get_metadata_for_entry_group)

    @property
    def extended_results(self) -> Iterable[list[dict[int, Result]]]:
        for frame_no in range(self.num_frames):
            yield self._get_result_for_all_entries(frame_no)

    def _get_result_for_all_entries(self, frame_no: int) -> list[dict[int, Result]]:
        def entry_group_to_result(entry_group):
            return Result(
                data_saturated=entry_group["result/data_saturated"][frame_no],
                frame_delayed=entry_group["result/frame_delayed"][frame_no],
                calibration_needed=entry_group["result/calibration_needed"][frame_no],
                temperature=entry_group["result/temperature"][frame_no],
                tick=entry_group["result/tick"][frame_no],
                frame=np.array(entry_group["result/frame"][frame_no]),
                # TODO: ResultContext could use some optimization (caching) in the future.
                context=ResultContext(
                    metadata=self._get_metadata_for_entry_group(entry_group),
                    ticks_per_second=self.server_info.ticks_per_second,
                ),
            )

        return self._map_over_entries(entry_group_to_result)

    @property
    def lib_version(self) -> str:
        return self._h5py_dataset_to_str(self.file["lib_version"])

    @property
    def num_frames(self) -> int:
        (num_frames,) = {len(entry["result/frame"]) for _, _, entry in self._iterate_entries()}
        return num_frames

    @property
    def server_info(self) -> ServerInfo:
        return ServerInfo.from_json(self.file["server_info"][()])

    @property
    def session_config(self) -> SessionConfig:
        return SessionConfig.from_json(self.file["session_config"][()])

    @property
    def timestamp(self) -> str:
        return self._h5py_dataset_to_str(self.file["timestamp"])

    @property
    def uuid(self) -> str:
        return self._h5py_dataset_to_str(self.file["uuid"])

    def close(self) -> None:
        self.file.close()

    def _get_entries(self) -> list[dict[int, h5py.Group]]:
        structure: dict[int, dict[int, h5py.Group]] = {}

        for k, v in self.file["session"].items():
            m = re.fullmatch(r"group_(\d+)", k)

            if not m:
                continue

            group_index = int(m.group(1))
            structure[group_index] = {}

            for vv in v.values():
                sensor_id = vv["sensor_id"][()]
                structure[group_index][sensor_id] = vv

        return [structure[i] for i in range(len(structure))]

    def _map_over_entries(self, func: Callable[[h5py.Group], T]) -> list[dict[int, T]]:
        structure = self._get_entries()
        return [{k: func(v) for k, v in d.items()} for d in structure]

    def _iterate_entries(self) -> Iterable[Tuple[int, int, h5py.Group]]:
        """Iterates over "Entry" items in this record.

        :returns: An iterable of <group_id>, <sensor_id>, <"EntryGroup">
        """
        for group_id, group_dict in enumerate(self._get_entries()):
            for sensor_id, entry_group in group_dict.items():
                yield (group_id, sensor_id, entry_group)

    @staticmethod
    def _get_metadata_for_entry_group(g: h5py.Group) -> Metadata:
        return Metadata.from_json(g["metadata"][()])

    @staticmethod
    def _h5py_dataset_to_str(dataset: h5py.Dataset) -> str:
        return bytes(dataset[()]).decode()
