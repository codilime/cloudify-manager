(where (metric > 0)
  (with :state "ok" (changed :state {:init "init"} process-policy-triggers)))
