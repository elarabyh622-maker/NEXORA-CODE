package main

func (s *Store) complete(id int) (Task, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	index, err := taskIndex(s.tasks, id)
	if err != nil {
		return Task{}, err
	}
	if s.tasks[index].Completed {
		return Task{}, ErrCompleted
	}
	s.tasks[index].Completed = true
	return s.tasks[index], nil
}
