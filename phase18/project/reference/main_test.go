package main

import (
	"encoding/json"
	"flag"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

var starter = flag.Bool("starter", false, "expect the unfinished complete method")

// This test owns an ephemeral loopback port and closes it before returning.
func TestLoopbackJourney(t *testing.T) {
	server := httptest.NewServer(newHandler(&Store{}))
	defer server.Close()
	client := server.Client()
	client.Timeout = 5 * time.Second
	steps := []struct {
		method, path, body string
		status             int
	}{
		{"GET", "/tasks", "", 200},
		{"POST", "/tasks", `{"title":"Local practice"}`, 201},
	}
	if *starter {
		steps = append(steps, struct {
			method, path, body string
			status             int
		}{"POST", "/tasks/1/complete", "", 501})
	} else {
		steps = append(steps, struct {
			method, path, body string
			status             int
		}{"POST", "/tasks/1/complete", "", 200})
	}
	steps = append(steps, struct {
		method, path, body string
		status             int
	}{"GET", "/tasks", "", 200})
	for _, step := range steps {
		req, err := http.NewRequest(step.method, server.URL+step.path, strings.NewReader(step.body))
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("Content-Type", "application/json")
		response, err := client.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		body, readErr := io.ReadAll(response.Body)
		response.Body.Close()
		if readErr != nil || response.StatusCode != step.status || !json.Valid(body) {
			t.Fatalf("loopback %s %s: status=%d body=%s error=%v", step.method, step.path, response.StatusCode, body, readErr)
		}
	}
}

func request(t *testing.T, handler http.Handler, method, path, body string, status int) *httptest.ResponseRecorder {
	t.Helper()
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(method, path, strings.NewReader(body)))
	if response.Code != status {
		t.Fatalf("%s %s: status=%d want=%d body=%s", method, path, response.Code, status, response.Body.String())
	}
	if !strings.HasPrefix(response.Header().Get("Content-Type"), "application/json") || !json.Valid(response.Body.Bytes()) {
		t.Fatal("response must be JSON")
	}
	return response
}

func TestListAndCreate(t *testing.T) {
	handler := newHandler(&Store{})
	initial := request(t, handler, "GET", "/tasks", "", 200)
	if strings.TrimSpace(initial.Body.String()) != "[]" {
		t.Fatal("initial list must be []")
	}
	created := request(t, handler, "POST", "/tasks", `{"title":"Learn Go"}`, 201)
	var task Task
	if err := json.Unmarshal(created.Body.Bytes(), &task); err != nil {
		t.Fatal(err)
	}
	if task.ID != 1 || task.Title != "Learn Go" || task.Completed {
		t.Fatalf("unexpected task: %+v", task)
	}
	listed := request(t, handler, "GET", "/tasks", "", 200)
	var tasks []Task
	if err := json.Unmarshal(listed.Body.Bytes(), &tasks); err != nil {
		t.Fatal(err)
	}
	if len(tasks) != 1 || tasks[0] != task {
		t.Fatalf("unexpected list: %+v", tasks)
	}
	request(t, handler, "POST", "/tasks", `{"title":"Practice"}`, 201)
}

func TestRejectedRequestsDoNotMutate(t *testing.T) {
	store := &Store{}
	handler := newHandler(store)
	cases := []struct {
		method, path, body string
		status             int
	}{
		{"POST", "/tasks", "", 400},
		{"POST", "/tasks", `{`, 400},
		{"POST", "/tasks", `null`, 400},
		{"POST", "/tasks", `{"title":""}`, 400},
		{"POST", "/tasks", `{"title":" x"}`, 400},
		{"POST", "/tasks", `{"title":"x "}`, 400},
		{"POST", "/tasks", `{"title":"x\ny"}`, 400},
		{"POST", "/tasks", `{"title":12}`, 400},
		{"POST", "/tasks", `{"title":"x","extra":true}`, 400},
		{"POST", "/tasks", `{"title":"x"} {}`, 400},
		{"POST", "/tasks", `{"title":"` + strings.Repeat("x", 121) + `"}`, 400},
		{"POST", "/tasks", strings.Repeat(" ", 4097), 413},
		{"POST", "/tasks", `{"title":"x"}` + strings.Repeat(" ", 4097), 413},
		{"POST", "/tasks/1/complete", "{}", 400},
		{"POST", "/tasks/1/complete", strings.Repeat("x", 4097), 413},
		{"POST", "/tasks/0/complete", "", 400},
		{"POST", "/tasks/01/complete", "", 400},
		{"POST", "/tasks/no/complete", "", 400},
		{"GET", "/missing", "", 404},
		{"GET", "/tasks/1/complete", "", 405},
		{"DELETE", "/tasks", "", 405},
	}
	for _, example := range cases {
		request(t, handler, example.method, example.path, example.body, example.status)
		if len(store.list()) != 0 {
			t.Fatal("rejected request changed tasks")
		}
	}
}

func TestComplete(t *testing.T) {
	store := &Store{}
	handler := newHandler(store)
	request(t, handler, "POST", "/tasks", `{"title":"Learn Go"}`, 201)
	request(t, handler, "POST", "/tasks", `{"title":"Practice"}`, 201)
	if *starter {
		request(t, handler, "POST", "/tasks/1/complete", "", 501)
		if store.list()[0].Completed {
			t.Fatal("unfinished complete changed state")
		}
		t.Log("PASSED: starter scaffolding; complete still requires implementation")
		return
	}
	request(t, handler, "POST", "/tasks/99/complete", "", 404)
	request(t, handler, "POST", "/tasks/1/complete", "", 200)
	tasks := store.list()
	if len(tasks) != 2 || !tasks[0].Completed || tasks[0].Title != "Learn Go" || tasks[1].Completed {
		t.Fatalf("completion changed wrong state: %+v", tasks)
	}
	request(t, handler, "POST", "/tasks/1/complete", "", 409)
	request(t, handler, "POST", "/tasks/2/complete", "", 200)
	if _, err := store.complete(0); err != ErrInvalid {
		t.Fatal("complete must reject invalid id")
	}
}

func TestStoreCopiesCapacityAndConcurrency(t *testing.T) {
	store := &Store{}
	var workers sync.WaitGroup
	for count := 0; count < 100; count++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			if _, err := store.create("Practice"); err != nil {
				t.Error(err)
			}
			_ = store.list()
		}()
	}
	workers.Wait()
	tasks := store.list()
	if len(tasks) != 100 {
		t.Fatalf("got %d tasks", len(tasks))
	}
	for index, task := range tasks {
		if task.ID != index+1 {
			t.Fatal("IDs must be unique and ordered")
		}
	}
	tasks[0].Title = "Changed outside store"
	if store.list()[0].Title != "Practice" {
		t.Fatal("list leaked store state")
	}
	request(t, newHandler(store), "POST", "/tasks", `{"title":"Overflow"}`, 409)
	if *starter {
		return
	}
	for _, task := range store.list() {
		workers.Add(1)
		go func(id int) {
			defer workers.Done()
			if _, err := store.complete(id); err != nil {
				t.Error(err)
			}
			_ = store.list()
		}(task.ID)
	}
	workers.Wait()
	for _, task := range store.list() {
		if !task.Completed {
			t.Fatal("concurrent completion lost an update")
		}
	}
}
