import pytest
import random
import logging
import datetime
import uuid
from unittest import mock
import unittest

from tests.utils import mock_base_gcp_hook_no_default_project_id, QueryJob
from airflow.providers.google.common.consts import CLIENT_INFO
from airflow_provider_bigquery_reservation.hooks.bigquery_reservation import (
    BigQueryReservationServiceHook,
)

from google.api_core import retry
from google.protobuf import field_mask_pb2
from google.cloud import bigquery

from google.cloud.bigquery_reservation_v1 import (
    ReservationServiceClient,
    CapacityCommitment,
    Reservation,
    Assignment,
    BiReservation,
    UpdateReservationRequest,
    DeleteAssignmentRequest,
    DeleteCapacityCommitmentRequest,
    DeleteReservationRequest,
    GetReservationRequest,
    SearchAllAssignmentsRequest,
    UpdateBiReservationRequest,
    GetBiReservationRequest,
)

from airflow.exceptions import AirflowException
from google.cloud.bigquery import DEFAULT_RETRY

LOGGER = logging.getLogger(__name__)
CREDENTIALS = "test-creds"
PROJECT_ID = "test-project"
LOCATION = "US"
SLOTS = 100
SLOTS_ALL = SLOTS + 100
SIZE = 100
SIZE_KO = 107374182400
COMMITMENT_DURATION = "FLEX"
PARENT = f"projects/{PROJECT_ID}/locations/{LOCATION}"
RESOURCE_NAME = "test"
RESOURCE_ID = "test"
JOB_TYPE = "QUERY"
STATE = "ACTIVE"
DAG_ID = "dag"
TASK_ID = "task"
LOGICAL_DATE = datetime.datetime.strptime("2023-01-01", "%Y-%m-%d")

# DEFAULT_RETRY = retry.Retry(deadline=90, predicate=Exception, maximum=2)


@pytest.fixture()
def logger():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    return logger


class TestBigQueryReservationHook:
    def default_exception():
        raise Exception("Test")

    def setup_method(self):
        with mock.patch(
            "airflow_provider_bigquery_reservation.hooks.bigquery_reservation.GoogleBaseHook.__init__",
            new=mock_base_gcp_hook_no_default_project_id,
        ):
            self.hook = BigQueryReservationServiceHook(location=LOCATION)
            self.hook.get_credentials = mock.MagicMock(return_value=CREDENTIALS)
            self.location = LOCATION

    @mock.patch("google.cloud.bigquery_reservation_v1.ReservationServiceClient")
    def test_get_client_already_exist(self, reservation_client_mock):
        expected = reservation_client_mock(
            credentials=self.hook.get_credentials(), client_info=CLIENT_INFO
        )
        self.hook._client = expected
        assert self.hook.get_client() == expected

    def test_verify_slots_conditions(self):
        valid_slots = 100 * random.randint(1, 1000)
        unvalid_slots = random.randint(0, 10) * 100 + random.randint(1, 99)

        assert self.hook._verify_slots_conditions(valid_slots) == None
        with pytest.raises(AirflowException):
            self.hook._verify_slots_conditions(unvalid_slots)

    def test_convert_gb_to_kb(self):
        value = random.randint(1, 1000)
        assert self.hook._convert_gb_to_kb(value) == value * 1073741824

    @mock.patch.object(
        uuid, "uuid4", return_value="e39dfcb7-dc5f-498d-8a89-5a871e9c4363"
    )
    def test_generate_resource_id(self, uuid_mock):
        expected = f"airflow--{DAG_ID}-{TASK_ID}--2023-01-01t00-00-00-3bfe"
        assert (
            self.hook.generate_resource_id(
                DAG_ID,
                TASK_ID,
                LOGICAL_DATE,
            )
            == expected
        )

    # Create Capacity Commitment
    @mock.patch(
        "airflow_provider_bigquery_reservation.hooks.bigquery_reservation.BigQueryReservationServiceHook.get_client"
    )
    def test_create_capacity_commitment_success(self, client_mock):
        result = self.hook.create_capacity_commitment(
            PARENT, SLOTS, COMMITMENT_DURATION
        )
        client_mock.return_value.create_capacity_commitment.assert_called_once_with(
            parent=PARENT,
            capacity_commitment=CapacityCommitment(
                plan=COMMITMENT_DURATION, slot_count=SLOTS
            ),
        )

    @mock.patch.object(
        ReservationServiceClient,
        "create_capacity_commitment",
        side_effect=Exception("Test"),
    )
    def test_create_capacity_commitment_failure(self, call_failure):
        with pytest.raises(AirflowException):
            self.hook.create_capacity_commitment(PARENT, SLOTS, COMMITMENT_DURATION)

    # Delete Capacity Commitment
    @mock.patch(
        "airflow_provider_bigquery_reservation.hooks.bigquery_reservation.BigQueryReservationServiceHook.get_client"
    )
    @mock.patch(
        "google.api_core.retry.Retry",
    )
    def test_delete_capacity_commitment_success(self, retry_mock, client_mock):
        result = self.hook.delete_capacity_commitment(RESOURCE_NAME)
        client_mock.return_value.delete_capacity_commitment.assert_called_once_with(
            name=RESOURCE_NAME,
            retry=retry_mock(),
        )

    @mock.patch.object(
        ReservationServiceClient,
        "delete_capacity_commitment",
        side_effect=Exception("Test"),
    )
    def test_delete_capacity_commitment_failure(self, call_failure):
        with pytest.raises(AirflowException):
            self.hook.delete_capacity_commitment(RESOURCE_NAME)

    # Create Reservation
    @mock.patch(
        "airflow_provider_bigquery_reservation.hooks.bigquery_reservation.BigQueryReservationServiceHook.get_client"
    )
    def test_create_reservation_success(self, client_mock):
        result = self.hook.create_reservation(
            PARENT,
            RESOURCE_ID,
            SLOTS,
        )
        client_mock.return_value.create_reservation.assert_called_once_with(
            parent=PARENT,
            reservation_id=RESOURCE_ID,
            reservation=Reservation(slot_capacity=SLOTS, ignore_idle_slots=True),
        ),

    @mock.patch.object(
        ReservationServiceClient, "create_reservation", side_effect=Exception("Test")
    )
    def test_create_reservation_failure(self, call_failure):
        with pytest.raises(AirflowException):
            self.hook.create_reservation(
                PARENT,
                RESOURCE_ID,
                SLOTS,
            )

    # Get Reservation
    @mock.patch(
        "airflow_provider_bigquery_reservation.hooks.bigquery_reservation.BigQueryReservationServiceHook.get_client"
    )
    def test_get_reservation_success(self, client_mock):
        expected = Reservation(name=RESOURCE_NAME)
        client_mock.return_value.get_reservation.return_value = expected

        result = self.hook.get_reservation(
            RESOURCE_NAME,
        )

        client_mock.return_value.get_reservation.assert_called_once_with(
            GetReservationRequest(
                name=RESOURCE_NAME,
            )
        ),

        assert result == expected

    @mock.patch.object(
        ReservationServiceClient, "get_reservation", side_effect=Exception("Test")
    )
    def test_get_reservation_failure(self, call_failure):
        with pytest.raises(AirflowException):
            self.hook.get_reservation(RESOURCE_NAME)

    # Update Reservation
    @mock.patch(
        "airflow_provider_bigquery_reservation.hooks.bigquery_reservation.BigQueryReservationServiceHook.get_client"
    )
    def test_update_reservation_success(self, client_mock):
        new_reservation = Reservation(name=RESOURCE_NAME, slot_capacity=SLOTS)
        field_mask = field_mask_pb2.FieldMask(paths=["slot_capacity"])
        result = self.hook.update_reservation(
            RESOURCE_NAME,
            SLOTS,
        )
        client_mock.return_value.update_reservation.assert_called_once_with(
            reservation=new_reservation, update_mask=field_mask
        )

    @mock.patch.object(
        ReservationServiceClient, "update_reservation", side_effect=Exception("Test")
    )
    def test_update_reservation_failure(self, call_failure):
        with pytest.raises(AirflowException):
            self.hook.update_reservation(RESOURCE_NAME, SLOTS)

    # Delete Reservation
    @mock.patch(
        "airflow_provider_bigquery_reservation.hooks.bigquery_reservation.BigQueryReservationServiceHook.get_client"
    )
    def test_delete_reservation_success(self, client_mock):
        result = self.hook.delete_reservation(RESOURCE_NAME)
        client_mock.return_value.delete_reservation.assert_called_once_with(
            request=DeleteReservationRequest(name=RESOURCE_NAME)
        )

    @mock.patch.object(
        ReservationServiceClient, "delete_reservation", side_effect=Exception("Test")
    )
    def test_delete_reservation_failure(self, call_failure):
        with pytest.raises(AirflowException):
            self.hook.delete_reservation(RESOURCE_NAME)

    # Create Assignment
    @mock.patch(
        "airflow_provider_bigquery_reservation.hooks.bigquery_reservation.BigQueryReservationServiceHook.get_client"
    )
    def test_create_assignment_success(self, client_mock):
        result = self.hook.create_assignment(PARENT, PROJECT_ID, JOB_TYPE)
        client_mock.return_value.create_assignment.assert_called_once_with(
            parent=PARENT,
            assignment=Assignment(job_type=JOB_TYPE, assignee=f"projects/{PROJECT_ID}"),
        )

    @mock.patch.object(
        ReservationServiceClient, "create_assignment", side_effect=Exception("Test")
    )
    def test_create_assignment_failure(self, call_failure):
        with pytest.raises(AirflowException):
            self.hook.create_assignment(PARENT, PROJECT_ID, JOB_TYPE)

    # Search Assignment
    @mock.patch(
        "airflow_provider_bigquery_reservation.hooks.bigquery_reservation.BigQueryReservationServiceHook.get_client"
    )
    def test_search_assignment_success_none_assignments(self, client_mock):
        result = self.hook.search_assignment(PARENT, PROJECT_ID, JOB_TYPE)
        client_mock.return_value.search_all_assignments.assert_called_once_with(
            request=SearchAllAssignmentsRequest(
                parent=PARENT, query=f"assignee=projects/{PROJECT_ID}"
            )
        )

    @mock.patch.object(
        ReservationServiceClient,
        "search_all_assignments",
        return_value=[
            Assignment(
                name=RESOURCE_NAME,
                assignee=PROJECT_ID,
                job_type="PIPELINE",
                state=STATE,
            ),
            Assignment(
                name=RESOURCE_NAME,
                assignee=PROJECT_ID,
                job_type=JOB_TYPE,
                state="PENDING",
            ),
            Assignment(
                name=RESOURCE_NAME, assignee=PROJECT_ID, job_type=JOB_TYPE, state=STATE
            ),
        ],
    )
    def test_search_assignment_success_have_assignments(self, search_all_mock):
        expected = Assignment(
            name=RESOURCE_NAME, assignee=PROJECT_ID, job_type=JOB_TYPE, state=STATE
        )
        result = self.hook.search_assignment(PARENT, PROJECT_ID, JOB_TYPE)

        assert result == expected

    @mock.patch.object(
        ReservationServiceClient,
        "search_all_assignments",
        return_value=[
            Assignment(
                name=RESOURCE_NAME,
                assignee=PROJECT_ID,
                job_type=JOB_TYPE,
                state="PENDING",
            )
        ],
    )
    def test_search_assignment_success_no_assignment(self, search_all_mock):
        result = self.hook.search_assignment(PARENT, PROJECT_ID, JOB_TYPE)
        assert result == None

    @mock.patch.object(
        ReservationServiceClient,
        "search_all_assignments",
        side_effect=Exception("Test"),
    )
    def test_search_assignment_failure(self, call_failure):
        with pytest.raises(AirflowException):
            self.hook.search_assignment(PARENT, PROJECT_ID, JOB_TYPE)

    # Delete Assignment
    @mock.patch(
        "airflow_provider_bigquery_reservation.hooks.bigquery_reservation.BigQueryReservationServiceHook.get_client"
    )
    def test_delete_assignment_success(self, client_mock):
        self.hook.delete_assignment(RESOURCE_NAME)
        client_mock.return_value.delete_assignment.assert_called_once_with(
            request=DeleteAssignmentRequest(
                name=RESOURCE_NAME,
            )
        )

    @mock.patch.object(
        ReservationServiceClient, "delete_assignment", side_effect=Exception("Test")
    )
    def test_delete_assignment_failure(self, call_failure):
        with pytest.raises(AirflowException):
            self.hook.delete_assignment(RESOURCE_NAME)

    # Get BQ client
    @mock.patch("google.cloud.bigquery.Client")
    def test_get_bq_client(self, bq_client_mock):
        assert self.hook.get_bq_client() == bq_client_mock(
            credentials=self.hook.get_credentials(), client_info=CLIENT_INFO
        )

    # Is Assignment attached
    @mock.patch("google.cloud.bigquery.QueryJobConfig")
    def test_is_assignment_attached_true(self, query_job_config_mock):
        bq_client = mock.MagicMock()
        bq_client.query.return_value = QueryJob(reservation_id=True)

        dummy_query = """
            SELECT dummy
            FROM UNNEST([STRUCT(true as dummy)])
        """
        job_config = bigquery.QueryJobConfig(use_query_cache=False)
        rslt = self.hook._is_assignment_attached_in_query(
            bq_client,
            PROJECT_ID,
            LOCATION,
        )
        bq_client.query.assert_called_with(
            dummy_query,
            project=PROJECT_ID,
            location=LOCATION,
            job_id_prefix="test_assignment_reservation",
            job_config=query_job_config_mock(),
        )

        assert rslt == True

    @mock.patch("google.cloud.bigquery.QueryJobConfig")
    def test_is_assignment_attached_false(self, query_job_config_mock):
        bq_client = mock.MagicMock()
        bq_client.query.return_value = QueryJob(reservation_id=False)

        dummy_query = """
            SELECT dummy
            FROM UNNEST([STRUCT(true as dummy)])
        """
        job_config = bigquery.QueryJobConfig(use_query_cache=False)
        rslt = self.hook._is_assignment_attached_in_query(
            bq_client,
            PROJECT_ID,
            LOCATION,
        )
        bq_client.query.assert_called_with(
            dummy_query,
            project=PROJECT_ID,
            location=LOCATION,
            job_id_prefix="test_assignment_reservation",
            job_config=query_job_config_mock(),
        )

        assert rslt == False

    # Create BI Reservation
    @mock.patch(
        "airflow_provider_bigquery_reservation.hooks.bigquery_reservation.BigQueryReservationServiceHook.get_client"
    )
    def test_create_bi_reservation_success(self, client_mock):
        client_mock.return_value.get_bi_reservation.return_value = BiReservation(
            name=RESOURCE_NAME, size=SIZE_KO
        )
        result = self.hook.create_bi_reservation(PARENT, SIZE)
        client_mock.return_value.get_bi_reservation.assert_called_once_with(
            request=GetBiReservationRequest(name=PARENT)
        )
        client_mock.return_value.update_bi_reservation.assert_called_once_with(
            request=UpdateBiReservationRequest(
                bi_reservation=BiReservation(name=RESOURCE_NAME, size=SIZE_KO)
            )
        )

    @mock.patch.object(
        ReservationServiceClient, "get_bi_reservation", side_effect=Exception("Test")
    )
    def test_create_bi_reservation_get_failure(self, call_failure):
        with pytest.raises(AirflowException):
            self.hook.create_bi_reservation(PARENT, SIZE)

    @mock.patch.object(ReservationServiceClient, "get_bi_reservation")
    @mock.patch.object(
        ReservationServiceClient, "update_bi_reservation", side_effect=Exception("Test")
    )
    def test_create_bi_reservation_update_failure(
        self, call_failure, get_bi_reservation_mock
    ):
        with pytest.raises(AirflowException):
            self.hook.create_bi_reservation(PARENT, SIZE)

    # Delete BI Reservation
    @mock.patch(
        "airflow_provider_bigquery_reservation.hooks.bigquery_reservation.BigQueryReservationServiceHook.get_client"
    )
    def test_delete_bi_reservation_success_update_to_0(self, client_mock):
        client_mock.return_value.get_bi_reservation.return_value = BiReservation(
            name=RESOURCE_NAME, size=SIZE_KO
        )
        result = self.hook.delete_bi_reservation(PARENT, SIZE)
        client_mock.return_value.get_bi_reservation.assert_called_once_with(
            request=GetBiReservationRequest(name=PARENT)
        )
        client_mock.return_value.update_bi_reservation.assert_called_once_with(
            request=UpdateBiReservationRequest(
                bi_reservation=BiReservation(name=RESOURCE_NAME, size=0)
            )
        )

    @mock.patch(
        "airflow_provider_bigquery_reservation.hooks.bigquery_reservation.BigQueryReservationServiceHook.get_client"
    )
    def test_delete_bi_reservation_success_update_non_negative(self, client_mock):
        client_mock.return_value.get_bi_reservation.return_value = BiReservation(
            name=RESOURCE_NAME, size=SIZE_KO - 10000
        )
        result = self.hook.delete_bi_reservation(PARENT, SIZE)
        client_mock.return_value.get_bi_reservation.assert_called_once_with(
            request=GetBiReservationRequest(name=PARENT)
        )
        client_mock.return_value.update_bi_reservation.assert_called_once_with(
            request=UpdateBiReservationRequest(
                bi_reservation=BiReservation(name=RESOURCE_NAME, size=0)
            )
        )

    @mock.patch.object(
        ReservationServiceClient, "get_bi_reservation", side_effect=Exception("Test")
    )
    def test_delete_bi_reservation_get_failure(self, call_failure):
        with pytest.raises(AirflowException):
            self.hook.delete_bi_reservation(PARENT, SIZE)

    @mock.patch.object(ReservationServiceClient, "get_bi_reservation")
    @mock.patch.object(
        ReservationServiceClient, "update_bi_reservation", side_effect=Exception("Test")
    )
    def test_delete_bi_reservation_update_failure(
        self, call_failure, get_bi_reservation_mock
    ):
        with pytest.raises(AirflowException):
            self.hook.delete_bi_reservation(PARENT, SIZE)

    # Create Commitment Reservation And Assignment
    @mock.patch.object(
        BigQueryReservationServiceHook,
        "create_capacity_commitment",
    )
    @mock.patch.object(
        BigQueryReservationServiceHook,
        "search_assignment",
        return_value=Assignment(
            name=RESOURCE_NAME, assignee=PROJECT_ID, job_type=JOB_TYPE, state=STATE
        ),
    )
    @mock.patch.object(
        BigQueryReservationServiceHook,
        "get_reservation",
        return_value=Reservation(name=RESOURCE_NAME, slot_capacity=SLOTS),
    )
    @mock.patch.object(BigQueryReservationServiceHook, "update_reservation")
    def test_create_commitment_reservation_and_assignment_success_existing_assignment(
        self,
        update_reservation_mock,
        get_reservation_mock,
        search_assignment_mock,
        create_capacity_commitment_mock,
    ):
        parent = f"projects/{PROJECT_ID}/locations/{self.location}"
        new_slots = get_reservation_mock.return_value.slot_capacity + SLOTS

        self.hook.create_commitment_reservation_and_assignment(
            resource_id=RESOURCE_ID,
            slots=SLOTS,
            assignment_job_type=JOB_TYPE,
            commitments_duration=COMMITMENT_DURATION,
            project_id=PROJECT_ID,
        )

        create_capacity_commitment_mock.assert_called_once_with(
            parent=parent, slots=SLOTS, commitments_duration=COMMITMENT_DURATION
        )

        get_reservation_mock.assert_called_once_with(name=RESOURCE_NAME)

        update_reservation_mock.assert_called_once_with(
            name=RESOURCE_NAME, slots=new_slots
        )

    @mock.patch.object(
        BigQueryReservationServiceHook,
        "create_capacity_commitment",
    )
    @mock.patch.object(
        BigQueryReservationServiceHook,
        "search_assignment",
        return_value=None,
    )
    @mock.patch.object(
        BigQueryReservationServiceHook,
        "create_reservation",
    )
    @mock.patch.object(BigQueryReservationServiceHook, "create_assignment")
    @mock.patch.object(BigQueryReservationServiceHook, "get_bq_client")
    @mock.patch.object(
        BigQueryReservationServiceHook,
        "_is_assignment_attached_in_query",
        return_value=True,
    )
    def test_create_commitment_reservation_and_assignment_success_not_existing_assignment(
        self,
        _is_assignment_attached_in_query_mock,
        bq_client_mock,
        create_assignment_mock,
        create_reservation_mock,
        search_assignment_mock,
        create_capacity_commitment_mock,
    ):
        parent = f"projects/{PROJECT_ID}/locations/{self.location}"
        self.hook.reservation = Reservation(name=RESOURCE_NAME, slot_capacity=SLOTS)

        self.hook.create_commitment_reservation_and_assignment(
            resource_id=RESOURCE_ID,
            slots=SLOTS,
            assignment_job_type=JOB_TYPE,
            commitments_duration=COMMITMENT_DURATION,
            project_id=PROJECT_ID,
        )

        create_capacity_commitment_mock.assert_called_once_with(
            parent=parent, slots=SLOTS, commitments_duration=COMMITMENT_DURATION
        )

        create_reservation_mock.assert_called_once_with(
            parent=parent, reservation_id=RESOURCE_NAME, slots=SLOTS
        )

        create_assignment_mock.assert_called_once_with(
            parent=RESOURCE_NAME,
            project_id=PROJECT_ID,
            job_type=JOB_TYPE,
        )

    @mock.patch.object(
        BigQueryReservationServiceHook,
        "create_capacity_commitment",
    )
    @mock.patch.object(
        BigQueryReservationServiceHook,
        "search_assignment",
        return_value=None,
    )
    @mock.patch.object(
        BigQueryReservationServiceHook,
        "create_reservation",
    )
    @mock.patch.object(BigQueryReservationServiceHook, "create_assignment")
    @mock.patch.object(BigQueryReservationServiceHook, "get_bq_client")
    @mock.patch.object(
        BigQueryReservationServiceHook,
        "_is_assignment_attached_in_query",
        side_effect=Exception("Test"),
    )
    @mock.patch.object(
        BigQueryReservationServiceHook, "delete_commitment_reservation_and_assignment"
    )
    def test_create_commitment_reservation_and_assignment_failure_query_fail(
        self,
        delete_commitment_reservation_and_assignment_mock,
        _is_assignment_attached_in_query_mock,
        bq_client_mock,
        create_assignment_mock,
        create_reservation_mock,
        search_assignment_mock,
        create_capacity_commitment_mock,
    ):
        with pytest.raises(AirflowException):
            parent = f"projects/{PROJECT_ID}/locations/{self.location}"
            self.hook.reservation = Reservation(name=RESOURCE_NAME)
            self.hook.commitment = CapacityCommitment(name=RESOURCE_NAME)
            self.hook.assignment = Assignment(name=RESOURCE_NAME)

            self.hook.create_commitment_reservation_and_assignment(
                resource_id=RESOURCE_ID,
                slots=SLOTS,
                assignment_job_type=JOB_TYPE,
                commitments_duration=COMMITMENT_DURATION,
                project_id=PROJECT_ID,
            )

            delete_commitment_reservation_and_assignment_mock.assert_called_once_with(
                commitment_name=RESOURCE_NAME,
                reservation_name=RESOURCE_NAME,
                assignment_name=RESOURCE_NAME,
            )

    @mock.patch.object(
        ReservationServiceClient,
        "create_capacity_commitment",
        side_effect=Exception("Test"),
    )
    @mock.patch.object(
        BigQueryReservationServiceHook, "delete_commitment_reservation_and_assignment"
    )
    def test_create_commitment_reservation_and_assignment_failure_none_create(
        self, delete_commitment_reservation_and_assignment_mock, call_failure
    ):
        with pytest.raises(AirflowException):
            self.hook.create_commitment_reservation_and_assignment(
                RESOURCE_ID,
                SLOTS,
                JOB_TYPE,
                COMMITMENT_DURATION,
                PROJECT_ID,
            )
            delete_commitment_reservation_and_assignment_mock.assert_called_once_with(
                commitment_name=None, reservation_name=None, assignment_name=None
            )

    # Delete Commitment Reservation And assignment
    def test_delete_commitment_reservation_and_assignment_none(self, caplog):
        self.hook.delete_commitment_reservation_and_assignment()
        assert "None BigQuery commitment to delete" in caplog.text
        assert "None BigQuery reservation to update or delete" in caplog.text

    @mock.patch.object(BigQueryReservationServiceHook, "delete_capacity_commitment")
    @mock.patch.object(BigQueryReservationServiceHook, "delete_reservation")
    @mock.patch.object(
        BigQueryReservationServiceHook,
        "get_reservation",
        return_value=Reservation(name=RESOURCE_NAME, slot_capacity=SLOTS),
    )
    def test_delete_commitment_reservation_and_assignment_false_slots_condition_none_assignment(
        self,
        get_reservation_mock,
        delete_reservation_mock,
        delete_capacity_commitment_mock,
        caplog,
    ):
        self.hook.delete_commitment_reservation_and_assignment(
            commitment_name=RESOURCE_NAME,
            reservation_name=RESOURCE_NAME,
            assignment_name=None,
            slots=SLOTS,
        )

        delete_capacity_commitment_mock.assert_called_once_with(name=RESOURCE_NAME)
        delete_reservation_mock.assert_called_once_with(name=RESOURCE_NAME)

        assert "None BigQuery assignment to update or delete" in caplog.text

    @mock.patch.object(BigQueryReservationServiceHook, "delete_capacity_commitment")
    @mock.patch.object(BigQueryReservationServiceHook, "delete_reservation")
    @mock.patch.object(BigQueryReservationServiceHook, "delete_assignment")
    @mock.patch.object(
        BigQueryReservationServiceHook,
        "get_reservation",
        return_value=Reservation(name=RESOURCE_NAME, slot_capacity=SLOTS),
    )
    def test_delete_commitment_reservation_and_assignment_false_slots_condition(
        self,
        get_reservation_mock,
        delete_assignment_mock,
        delete_reservation_mock,
        delete_capacity_commitment_mock,
    ):
        self.hook.delete_commitment_reservation_and_assignment(
            commitment_name=RESOURCE_NAME,
            reservation_name=RESOURCE_NAME,
            assignment_name=RESOURCE_NAME,
            slots=SLOTS,
        )

        delete_capacity_commitment_mock.assert_called_once_with(name=RESOURCE_NAME)
        delete_reservation_mock.assert_called_once_with(name=RESOURCE_NAME)
        delete_assignment_mock.assert_called_once_with(name=RESOURCE_NAME)

    @mock.patch.object(BigQueryReservationServiceHook, "update_reservation")
    @mock.patch.object(
        BigQueryReservationServiceHook,
        "get_reservation",
        return_value=Reservation(name=RESOURCE_NAME, slot_capacity=SLOTS_ALL),
    )
    def test_delete_commitment_reservation_and_assignment_true_slots_condition(
        self, get_reservation_mock, update_reservation_mock
    ):
        self.hook.delete_commitment_reservation_and_assignment(
            reservation_name=RESOURCE_NAME,
            slots=SLOTS,
        )

        new_slots = SLOTS_ALL - SLOTS

        update_reservation_mock.assert_called_once_with(
            name=RESOURCE_NAME, slots=new_slots
        )

    @mock.patch.object(
        ReservationServiceClient,
        "delete_capacity_commitment",
        side_effect=Exception("Test"),
    )
    def test_delete_commitment_reservation_failure(self, call_failure):
        with pytest.raises(AirflowException):
            self.hook.delete_commitment_reservation_and_assignment(
                commitment_name=RESOURCE_NAME,
            )