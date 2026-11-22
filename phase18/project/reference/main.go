package main

import (
	"encoding/json"
	"errors"
	"io"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"
)

func main() {
	server := &http.Server{
		Addr:              "127.0.0.1:8080",
		Handler:           newHandler(&Store{}),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       10 * time.Second,
		WriteTimeout:      10 * time.Second,
		IdleTimeout:       30 * time.Second,
		MaxHeaderBytes:    8 * 1024,
	}
	log.Println("Tasks API: http://127.0.0.1:8080 (Ctrl+C to stop)")
	log.Fatal(server.ListenAndServe())
}

func newHandler(store *Store) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/tasks" {
			switch r.Method {
			case http.MethodGet:
				writeJSON(w, http.StatusOK, store.list())
			case http.MethodPost:
				var input struct {
					Title string `json:"title"`
				}
				r.Body = http.MaxBytesReader(w, r.Body, 4096)
				decoder := json.NewDecoder(r.Body)
				decoder.DisallowUnknownFields()
				if err := decoder.Decode(&input); err != nil {
					bodyError(w, err)
					return
				}
				var extra any
				if err := decoder.Decode(&extra); err != io.EOF {
					bodyError(w, err)
					return
				}
				task, err := store.create(input.Title)
				if err != nil {
					storeError(w, err)
					return
				}
				writeJSON(w, http.StatusCreated, task)
			default:
				w.Header().Set("Allow", "GET, POST")
				writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			}
			return
		}
		parts := strings.Split(strings.TrimPrefix(r.URL.Path, "/"), "/")
		if len(parts) != 3 || parts[0] != "tasks" || parts[2] != "complete" {
			writeError(w, http.StatusNotFound, "route not found")
			return
		}
		if r.Method != http.MethodPost {
			w.Header().Set("Allow", "POST")
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return
		}
		id, err := strconv.Atoi(parts[1])
		if err != nil || id < 1 || strconv.Itoa(id) != parts[1] {
			writeError(w, http.StatusBadRequest, "invalid task id")
			return
		}
		body, err := io.ReadAll(http.MaxBytesReader(w, r.Body, 4096))
		if err != nil {
			bodyError(w, err)
			return
		}
		if len(body) != 0 {
			writeError(w, http.StatusBadRequest, "complete requires an empty body")
			return
		}
		task, err := store.complete(id)
		if err != nil {
			storeError(w, err)
			return
		}
		writeJSON(w, http.StatusOK, task)
	})
}

func bodyError(w http.ResponseWriter, err error) {
	var limit *http.MaxBytesError
	if errors.As(err, &limit) {
		writeError(w, http.StatusRequestEntityTooLarge, "body exceeds 4096 bytes")
		return
	}
	writeError(w, http.StatusBadRequest, "invalid JSON body")
}

func storeError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, ErrInvalid):
		writeError(w, http.StatusBadRequest, err.Error())
	case errors.Is(err, ErrNotFound):
		writeError(w, http.StatusNotFound, err.Error())
	case errors.Is(err, ErrCompleted), errors.Is(err, ErrCapacity):
		writeError(w, http.StatusConflict, err.Error())
	case errors.Is(err, ErrIncomplete):
		writeError(w, http.StatusNotImplemented, err.Error())
	default:
		writeError(w, http.StatusInternalServerError, "internal error")
	}
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}
