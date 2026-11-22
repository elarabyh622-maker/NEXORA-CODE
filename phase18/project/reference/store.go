package main

import (
	"errors"
	"strings"
	"sync"
	"unicode"
	"unicode/utf8"
)

var (
	ErrInvalid    = errors.New("invalid task")
	ErrNotFound   = errors.New("task not found")
	ErrCompleted  = errors.New("task already completed")
	ErrCapacity   = errors.New("task limit reached")
	ErrIncomplete = errors.New("complete is incomplete")
)

type Task struct {
	ID        int    `json:"id"`
	Title     string `json:"title"`
	Completed bool   `json:"completed"`
}

// Store protects every access to its tasks with one mutex.
type Store struct {
	mu    sync.Mutex
	tasks []Task
}

func (s *Store) list() []Task {
	s.mu.Lock()
	defer s.mu.Unlock()
	result := make([]Task, len(s.tasks))
	copy(result, s.tasks)
	return result
}

func (s *Store) create(title string) (Task, error) {
	if !utf8.ValidString(title) || strings.TrimSpace(title) != title || utf8.RuneCountInString(title) < 1 || utf8.RuneCountInString(title) > 120 {
		return Task{}, ErrInvalid
	}
	for _, character := range title {
		if unicode.IsControl(character) {
			return Task{}, ErrInvalid
		}
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if len(s.tasks) >= 100 {
		return Task{}, ErrCapacity
	}
	task := Task{ID: len(s.tasks) + 1, Title: title}
	s.tasks = append(s.tasks, task)
	return task, nil
}

// taskIndex is called only while the store mutex is held.
func taskIndex(tasks []Task, id int) (int, error) {
	if id < 1 {
		return -1, ErrInvalid
	}
	for index, task := range tasks {
		if task.ID == id {
			return index, nil
		}
	}
	return -1, ErrNotFound
}
