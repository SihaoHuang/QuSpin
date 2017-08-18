from __future__ import print_function, division

from ..basis import spin_basis_1d as _default_basis
from ..basis import isbasis as _isbasis

import exp_op

from .make_hamiltonian import make_static as _make_static
from .make_hamiltonian import make_dynamic as _make_dynamic
from .make_hamiltonian import test_function as _test_function
from ._functions import function

# need linear algebra packages
import scipy
import scipy.sparse.linalg as _sla
import scipy.linalg as _la
import scipy.sparse as _sp
import numpy as _np

from operator import mul
import functools
from six import iteritems,itervalues,viewkeys


from copy import deepcopy as _deepcopy # recursively copies all data into new object
from copy import copy as _shallowcopy # copies only at top level references the data of old objects
import warnings


__all__ = ["commutator","anti_commutator","hamiltonian","ishamiltonian"]

def commutator(H1,H2):
	""" This function returns the commutator of two Hamiltonians H1 and H2. """
	if ishamiltonian(H1) or ishamiltonian(H2):
		return H1*H2 - H2*H1
	else:
		return H1.dot(H2) - H2.dot(H1)

def anti_commutator(H1,H2):
	""" This function returns the anti-commutator of two Hamiltonians H1 and H2. """
	if ishamiltonian(H1) or ishamiltonian(H2):
		return H1*H2 + H2*H1
	else:
		return H1.dot(H2) + H2.dot(H1)


class HamiltonianEfficiencyWarning(Warning):
	pass


#global names:
supported_dtypes=tuple([_np.float32, _np.float64, _np.complex64, _np.complex128])

def _check_static(sub_list):
	if (type(sub_list) in [list,tuple]) and (len(sub_list) == 2):
		if type(sub_list[0]) is not str: raise TypeError('expecting string type for opstr')
		if type(sub_list[1]) in [list,tuple]:
			for sub_sub_list in sub_list[1]:
				if (type(sub_sub_list) in [list,tuple]) and (len(sub_sub_list) > 0):
					for element in sub_sub_list:
						if not _np.isscalar(element): raise TypeError('expecting scalar elements of indx')
				else: raise TypeError('expecting list for indx') 
		else: raise TypeError('expecting a list of one or more indx')
		return True
	else: 
		return False
	

def _check_dynamic(sub_list):
	if (type(sub_list) in [list,tuple]):
		if (len(sub_list) == 4):
			if type(sub_list[0]) is not str: raise TypeError('expecting string type for opstr')
			if type(sub_list[1]) in [list,tuple]:
				for sub_sub_list in sub_list[1]:
					if (type(sub_sub_list) in [list,tuple]) and (len(sub_sub_list) > 0):
						for element in sub_sub_list:
							if not _np.isscalar(element): raise TypeError('expecting scalar elements of indx')
					else: raise TypeError('expecting list for indx') 
			else: raise TypeError('expecting a list of one or more indx')
			if not hasattr(sub_list[2],"__call__"): raise TypeError('expecting callable object for driving function')
			if type(sub_list[3]) not in [list,tuple]: raise TypeError('expecting list for function arguments')
			return True
		elif (len(sub_list) == 3):
			if not hasattr(sub_list[1],"__call__"): raise TypeError('expecting callable object for driving function')
			if type(sub_list[2]) not in [list,tuple]: raise TypeError('expecting list for function arguments')
			return False
		elif (len(sub_list) == 2):
			if not hasattr(sub_list[1],"__call__"): raise TypeError('expecting callable object for driving function')
			return False
	else:
		raise TypeError('expecting list with object, driving function, and function arguments')



def _check_almost_zero(matrix):
	atol = 100*_np.finfo(matrix.dtype).eps

	if _sp.issparse(matrix):
		return _np.allclose(matrix.data,0,atol=atol)
	else:
		return _np.allclose(matrix,0,atol=atol)



# used to create linear operator of a hamiltonian
def _hamiltonian_dot(hamiltonian,time,v):
	return hamiltonian.dot(v,time=time,check=False)

class hamiltonian(object):
	def __init__(self,static_list,dynamic_list,N=None,shape=None,copy=True,check_symm=True,check_herm=True,check_pcon=True,dtype=_np.complex128,**kwargs):
		"""
		This function intializes the Hamtilonian. You can either initialize with symmetries, or an instance of basis.
		Note that if you initialize with a basis it will ignore all symmetry inputs.

		--- arguments ---

		* static_list: (compulsory) list of objects to calculate the static part of hamiltonian operator. The format goes like:

			```python
			static_list=[[opstr_1,[indx_11,...,indx_1m]],matrix_2,...]
			```
	

		* dynamic_list: (compulsory) list of objects to calculate the dynamic part of the hamiltonian operator.The format goes like:

			```python
			dynamic_list=[[opstr_1,[indx_11,...,indx_1n],func_1,func_1_args],[matrix_2,func_2,func_2_args],...]
			```

			For the dynamic list the ```func``` is the function which goes in front of the matrix or operator given in the same list. ```func_args``` is a tuple of the extra arguments which go into the function to evaluate it like: 
			```python
			f_val = func(t,*func_args)
			```


		* N: (optional) number of sites to create the hamiltonian with.

		* shape: (optional) shape to create the hamiltonian with.

		* copy: (optional) weather or not to copy the values from the input arrays. 

		* check_symm: (optional) flag whether or not to check the operator strings if they obey the given symmetries.

		* check_herm: (optional) flag whether or not to check if the operator strings create hermitian matrix. 

		* check_pcon: (optional) flag whether or not to check if the oeprator string whether or not they conserve magnetization/particles. 

		* dtype: (optional) data type to case the matrices with. 

		* kw_args: extra options to pass to the basis class.

		--- hamiltonian attributes ---: '_. ' below stands for 'object. '
		* _.basis: the basis associated with this hamiltonian, is None if hamiltonian has no basis. 

		* _.ndim: number of dimensions, always 2.
		
		* _.Ns: number of states in the hilbert space.

		* _.get_shape: returns tuple which has the shape of the hamiltonian (Ns,Ns)

		* _.is_dense: return 'True' if the hamiltonian contains a dense matrix as a componnent. 

		* _.dtype: returns the data type of the hamiltonian

		* _.static: return the static part of the hamiltonian 

		* _.dynamic: returns the dynamic parts of the hamiltonian 


		"""

		self._is_dense = False
		self._ndim = 2



		if not (dtype in supported_dtypes):
			raise TypeError('hamiltonian does not support type: '+str(dtype))
		else:
			self._dtype=dtype
		


		if type(static_list) in [list,tuple]:
			static_opstr_list=[]
			static_other_list=[]
			for ele in static_list:
				if _check_static(ele):
					static_opstr_list.append(ele)
				else:
					static_other_list.append(ele)
		else: 
			raise TypeError('expecting list/tuple of lists/tuples containing opstr and list of indx')

		if type(dynamic_list) in [list,tuple]:
			dynamic_opstr_list=[]
			dynamic_other_list=[]
			for ele in dynamic_list:
				if _check_dynamic(ele):
					dynamic_opstr_list.append(ele)
				else: 
					dynamic_other_list.append(ele)					
		else: 
			raise TypeError('expecting list/tuple of lists/tuples containing opstr and list of indx, functions, and function args')

		# need for check_symm
		self._static_opstr_list = static_opstr_list
		self._dynamic_opstr_list = dynamic_opstr_list
		self._basis=kwargs.get("basis")
		if self._basis is not None:
			kwargs.pop('basis')

		# if any operator strings present must get basis.
		if static_opstr_list or dynamic_opstr_list:
			if self._basis is not None:
				if len(kwargs) > 0:
					wrong_keys = set(kwargs.keys())
					temp = ", ".join(["{}" for key in wrong_keys])
					raise ValueError(("unexpected optional argument(s): "+temp).format(*wrong_keys))

			# if not
			if self._basis is None: 
				if N is None: # if L is missing 
					raise Exception('if opstrs in use, argument N needed for basis class')

				if type(N) is not int: # if L is not int
					raise TypeError('argument N must be integer')

				self._basis=_default_basis(N,**kwargs)

			elif not _isbasis(self._basis):
				raise TypeError('expecting instance of basis class for argument: basis')

			if check_herm:
				self._basis.check_hermitian(static_opstr_list, dynamic_opstr_list)

			if check_symm:
				self._basis.check_symm(static_opstr_list,dynamic_opstr_list)

			if check_pcon:
				self._basis.check_pcon(static_opstr_list,dynamic_opstr_list)



			self._static=_make_static(self._basis,static_opstr_list,dtype)
			self._dynamic=_make_dynamic(self._basis,dynamic_opstr_list,dtype)
			self._shape = self._static.shape

		


		if static_other_list or dynamic_other_list:
			if not hasattr(self,"_shape"):
				found = False
				if shape is None: # if no shape argument found, search to see if the inputs have shapes.
					for O in static_other_list:
						try: # take the first shape found
							shape = O.shape
							found = True
							break
						except AttributeError: 
							continue

					if not found:
						for tup in dynamic_other_list:
							if len(tup) == 2:
								O,_ = tup
							else:
								O,_,_ = tup
								
							try:
								shape = O.shape
								found = True
								break
							except AttributeError:
								continue
				else:
					found = True

				if not found:
					raise ValueError('missing argument shape')
				if shape[0] != shape[1]:
					raise ValueError('hamiltonian must be square matrix')

				self._shape=shape
				self._static = _sp.csr_matrix(self._shape,dtype=self._dtype)
				self._dynamic = {}

			for O in static_other_list:
				if _sp.issparse(O):
					self._mat_checks(O)

					try:
						self._static += O.astype(self._dtype)
					except NotImplementedError:
						self._static = self._static + O.astype(self._dtype)

				elif O.__class__ is _np.ndarray:
					self._mat_checks(O)

					self._is_dense=True
					try:
						self._static += O.astype(self._dtype)
					except NotImplementedError:
						self._static = self._static + O.astype(self._dtype)

				elif O.__class__ is _np.matrix:
					self._mat_checks(O)

					self._is_dense=True
					try:
						self._static += O.astype(self._dtype)
					except NotImplementedError:
						self._static = self._static + O.astype(self._dtype)
				else:
					O = _np.asanyarray(O)
					self._mat_checks(O)

					self._is_dense=True			
					try:
						self._static += O.astype(self._dtype)
					except NotImplementedError:
						self._static = self._static + O.astype(self._dtype)

			try:
				self._static = self._static.tocsr(copy=False)
				self._static.sum_duplicates()
				self._static.eliminate_zeros()
			except: pass



			for	tup in dynamic_other_list:
				if len(tup) == 2:
					O,func = tup
				else:
					O,f,f_args = tup
					_test_function(f,f_args)
					func = function(f,tuple(f_args))

				if _sp.issparse(O):
					self._mat_checks(O)

					O = O.astype(self._dtype)
					
				elif O.__class__ is _np.ndarray:
					self._mat_checks(O)
					self._is_dense=True

					O = _np.array(O,dtype=self._dtype,copy=copy)


				elif O.__class__ is _np.matrix:
					self._mat_checks(O)
					self._is_dense=True

					O = _np.array(O,dtype=self._dtype,copy=copy)

				else:
					O = _np.asanyarray(O)
					self._mat_checks(O)
					self._is_dense=True


				if func in self._dynamic:
					try:
						self._dynamic[func] += O
					except:
						self._dynamic[func] = self._dynamic[func] + O
				else:
					self._dynamic[func] = O


		else:
			if not hasattr(self,"_shape"):
				if shape is None:
					# if not
					if self._basis is None: 
						if N is None: # if N is missing 
							raise Exception("argument N or shape needed to create empty hamiltonian")

						if type(N) is not int: # if L is not int
							raise TypeError('argument N must be integer')

						self._basis=_default_basis(N,**kwargs)

					elif not _isbasis(basis):
						raise TypeError('expecting instance of basis class for argument: basis')

					shape = (basis.Ns,basis.Ns)

				else:
					self._basis=kwargs.get('basis')	
					if not basis is None: 
						raise ValueError("empty hamiltonian only accepts basis or shape, not both")

			
				if len(shape) != 2:
					raise ValueError('expecting ndim = 2')
				if shape[0] != shape[1]:
					raise ValueError('hamiltonian must be square matrix')

				self._shape=shape
				self._static = _sp.csr_matrix(self._shape,dtype=self._dtype)
				self._dynamic = {}

		self._Ns = self._shape[0]

	@property
	def basis(self):
		if self._basis is not None:
			return self._basis
		else:
			raise AttributeError("object has no attribute 'basis'")

	@property
	def ndim(self):
		return self._ndim
	
	@property
	def Ns(self):
		return self._Ns

	@property
	def get_shape(self):
		return self._shape

	@property
	def get_shape(self):
		return self._shape

	@property
	def is_dense(self):
		return self._is_dense

	@property
	def dtype(self):
		return _np.dtype(self._dtype).name

	@property
	def static(self):
		return self._static

	@property
	def dynamic(self):
		return self._dynamic

	@property
	def T(self):
		return self.transpose()

	@property
	def H(self):
		return self.getH()


	def check_is_dense(self):
		is_sparse = _sp.issparse(self._static)
		for Hd in itervalues(self._dynamic):
			is_sparse *= _sp.issparse(Hd)

		self._is_dense = not is_sparse

	

	def dot(self,V,time=0,check=True):
		"""
		args:
			V, the vector to multiple with
			time=0, the time to evalute drive at.

		description:
			This function does the spare matrix vector multiplication of V with the Hamiltonian evaluated at 
			the specified time. It is faster in this case to multiple each individual parts of the Hamiltonian 
			first, then add all those vectors together.
		"""

		
		if self.Ns <= 0:
			return _np.asarray([])

		if ishamiltonian(V):
			raise ValueError("To multiply hamiltonians use '*' operator.")


		if _np.array(time).ndim > 0:
			if V.ndim > 3:
				raise ValueError("Expecting V.ndim < 4.")


			time = _np.asarray(time)
			if time.ndim > 1:
				raise ValueError("Expecting time to be one dimensional array-like.")

			if _sp.issparse(V):
				if V.shape[1] == time.shape[0]:
					V = V.tocsc()
					return _sp.vstack([self.dot(V.get_col(i),time=t,check=check) for i,t in enumerate(time)])
				else:
					raise ValueError("For non-scalar times V.shape[-1] must be equal to len(time).")
			else:
				V = _np.asarray(V)
				if V.ndim == 2 and V.shape[-1] == time.shape[0]:
					if V.shape[0] != self._shape[1]:
						raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(V.shape,self._shape))

					V = V.T
					V_dot = _np.vstack([self.dot(v,time=t,check=check) for v,t in zip(V[:],time)]).T
					return V_dot

				elif V.ndim == 3 and V.shape[-1] == time.shape[0]:
					if V.shape[0] != self._shape[1]:
						raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(V.shape,self._shape))

					if V.shape[0] != V.shape[1]:
						raise ValueError("Density matricies must be square!")

					V = V.transpose((2,0,1))
					V_dot = _np.dstack([self.dot(v,time=t,check=check) for v,t in zip(V[:],time)])

					return V_dot

				else:
					raise ValueError("For non-scalar times V.shape[-1] must be equal to len(time).")
		else:	
			if not check:
				V_dot = self._static.dot(V)	
				for func,Hd in iteritems(self._dynamic):
					V_dot += func(time)*(Hd.dot(V))

				return V_dot

			if V.__class__ is _np.ndarray:
				if V.shape[0] != self._shape[1]:
					raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(V.shape,self._shape))
		
				V_dot = self._static.dot(V)	
				for func,Hd in iteritems(self._dynamic):
					V_dot += func(time)*(Hd.dot(V))


			elif _sp.issparse(V):
				if V.shape[0] != self._shape[1]:
					raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(V.shape,self._shape))
		
				V_dot = self._static * V
				for func,Hd in iteritems(self._dynamic):
					V_dot += func(time)*(Hd.dot(V))
				return V_dot

			elif V.__class__ is _np.matrix:
				if V.shape[0] != self._shape[1]:
					raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(V.shape,self._shape))

				V_dot = self._static.dot(V)	
				for func,Hd in iteritems(self._dynamic):
					V_dot += func(time)*(Hd.dot(V))

			else:
				V = _np.asanyarray(V)
				if V.ndim not in [1,2]:
					raise ValueError("Expecting 1 or 2 dimensional array")

				if V.shape[0] != self._shape[1]:
					raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(V.shape,self._shape))

				V_dot = self._static.dot(V)	
				for func,Hd in iteritems(self._dynamic):
					V_dot += func(time)*(Hd.dot(V))

			return V_dot



	def expt_value(self,V,time=0,check=True,enforce_pure=False):
		"""
		args:
			V: state or collection of states (pure or mixed)
			time: time to evaluate hamiltonian at.
			check: flag to tel whether or not to do check
			enforce_pure: flag to enforce pure expectation value of V is square. 
		"""
		if self.Ns <= 0:
			return _np.asarray([])

		if ishamiltonian(V):
			raise TypeError("Can't take expectation value of hamiltonian")

		if exp_op.isexp_op(V):
			raise TypeError("Can't take expectation value of exp_op")

		
		V_dot = self.dot(V,time=time,check=check)
		if _np.array(time).ndim > 0: # multiple time point expectation values
			if _sp.issparse(V): # multiple pure states multiple time points
				return (V.H.dot(V_dot)).diagonal()
			else:
				V = _np.asarray(V)
				if V.ndim == 2: # multiple pure states multiple time points
					return _np.einsum("ij,ij->j",V.conj(),V_dot)
				elif V.ndim == 3: # multiple mixed states multiple time points
					return _np.einsum("iij->j",V_dot)

		else:

			if _sp.issparse(V):
				if V.shape[0] != V.shape[1]: # pure states
					return _np.asscalar((V.H.dot(V_dot)).toarray())
				else: # density matrix
					return V.diagonal().sum()
			else:
				V_dot = _np.asarray(V_dot).squeeze()
				if V.ndim == 1: # pure state
					return _np.vdot(V,V_dot)
				elif (V.ndim == 2 and V.shape[0] != V.shape[1]) or enforce_pure: # multiple pure states
					return _np.einsum("ij,ij->j",V.conj(),V_dot)
				else: # density matrix
					return V_dot.trace()



			
	def matrix_ele(self,Vl,Vr,time=0,diagonal=False,check=True):
		"""
		args:
			Vl, the vector(s) to multiple with on left side
			Vr, the vector(s) to multiple with on the right side
			time=0, the time to evalute drive at.

		description:
			This function takes the matrix element of the Hamiltonian at the specified time
			between Vl and Vr.
		"""
		if self.Ns <= 0:
			return np.array([])

		Vr=self.dot(Vr,time=time,check=check)

		if not check:
			if diagonal:
				return _np.einsum("ij,ij->j",Vl.conj(),Vr)
			else:
				return Vl.T.conj().dot(Vr)
 
		if Vr.ndim > 2:
			raise ValueError('Expecting Vr to have ndim < 3')

		if Vl.__class__ is _np.ndarray:
			if Vl.ndim == 1:
				if Vl.shape[0] != self._shape[1]:
					raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(V1.shape,self._shape))

				return Vl.conj().dot(Vr)
			elif Vl.ndim == 2:
				if Vl.shape[0] != self._shape[1]:
					raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(V1.shape,self._shape))

				if diagonal:
					return _np.einsum("ij,ij->j",Vl.conj(),Vr)
				else:
					return Vl.T.conj().dot(Vr)
			else:
				raise ValueError('Expecting Vl to have ndim < 3')

		elif Vl.__class__ is _np.matrix:
			if Vl.ndim == 1:
				if Vl.shape[0] != self._shape[1]:
					raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(V1.shape,self._shape))

				return Vl.conj().dot(Vr)
			elif Vl.ndim == 2:
				if Vl.shape[0] != self._shape[1]:
					raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(V1.shape,self._shape))

				if diagonal:
					return _np.einsum("ij,ij->j",Vl.conj(),Vr)
				else:
					return Vl.H.dot(Vr)

		elif _sp.issparse(Vl):
			if Vl.shape[0] != self._shape[1]:
				raise ValueError('dimension mismatch')
			if diagonal:
				return Vl.H.dot(Vr).diagonal()
			else:
				return Vl.H.dot(Vr)

		else:
			Vl = _np.asanyarray(Vl)
			if Vl.ndim == 1:
				if Vl.shape[0] != self._shape[1]:
					raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(V1.shape,self._shape))
				if diagonal:
					return _np.einsum("ij,ij->j",Vl.conj(),Vr)
				else:
					return Vl.conj().dot(Vr)
			elif Vl.ndim == 2:
				if Vl.shape[0] != self._shape[1]:
					raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(V1.shape,self._shape))

				return Vl.T.conj().dot(Vr)
			else:
				raise ValueError('Expecting Vl to have ndim < 3')
		

	def project_to(self,proj):
		if ishamiltonian(proj):
			new = self._rmul_hamiltonian(proj.getH())
			return new._imul_hamiltonian(proj)

		elif exp_op.isexp_op(proj):
			return proj.sandwich(self)

		elif _sp.issparse(proj):
			if self._shape[1] != proj.shape[0]:
				raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(proj.shape,self._shape))
					
			new = self._rmul_sparse(proj.getH())
			new._shape = (proj.shape[1],proj.shape[1])
			return new._imul_sparse(proj)

		elif _np.isscalar(proj):
			raise NotImplementedError

		elif proj.__class__ == _np.ndarray:
			if self._shape[1] != proj.shape[0]:
				raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(proj.shape,self._shape))

			new = self._rmul_dense(proj.T.conj())
			new._shape = (proj.shape[1],proj.shape[1])
			return new._imul_dense(proj)


		elif proj.__class__ == _np.matrix:
			if self._shape[1] != proj.shape[0]:
				raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(proj.shape,self._shape))

			new = self._rmul_dense(proj.H)
			new._shape = (proj.shape[1],proj.shape[1])
			return new._imul_dense(proj)


		else:
			proj = _np.asanyarray(proj)
			if self._shape[1] != proj.shape[0]:
				raise ValueError("matrix dimension mismatch with shapes: {0} and {1}.".format(proj.shape,self._shape))

			new = self._rmul_dense(proj.T.conj())
			new._shape = (proj.shape[1],proj.shape[1])
			return new._imul_dense(proj)

	def rotate_by(self, other, generator=False, a=1.0, time=0.0,start=None, stop=None, num=None, endpoint=None, iterate=False):
		if generator:
			return exp_op(other,a=a,time=time,start=start,stop=stop,num=num,endpoint=endpoint,iterate=iterate).sandwich(self)
		else:
			return self.project_to(other)


	def eigsh(self,time=0,**eigsh_args):
		"""
		args:
			time=0, the time to evalute drive at.
			other arguments see documentation: http://docs.scipy.org/doc/scipy-0.14.0/reference/generated/scipy.sparse.linalg.eigsh.html
			
		description:
			function which diagonalizes hamiltonian using sparse methods
			solves for eigen values and eigen vectors, but can only solve for a few of them accurately.
			uses the scipy.sparse.linalg.eigsh function which is a wrapper for ARPACK
		"""
		if _np.array(time).ndim > 0:
			raise TypeError('expecting scalar argument for time')

		if self.Ns <= 0:
			return _np.asarray([]), _np.asarray([[]])

		return _sla.eigsh(self.tocsr(time=time),**eigsh_args)


	def eigh(self,time=0,**eigh_args):
		"""
		args:
			time=0, time to evaluate drive at.

		description:
			function which diagonalizes hamiltonian using dense methods solves for eigen values. 
			uses wrapped lapack functions which are contained in module py_lapack
		"""
		eigh_args["overwrite_a"] = True
		
		if _np.array(time).ndim > 0:
			raise TypeError('expecting scalar argument for time')


		if self.Ns <= 0:
			return _np.asarray([]),_np.asarray([[]])

		# fill dense array with hamiltonian
		H_dense = self.todense(time=time)		
		# calculate eigh
		E,H_dense = _la.eigh(H_dense,**eigh_args)
		return E,H_dense


	def eigvalsh(self,time=0,**eigvalsh_args):
		"""
		args:
			time=0, time to evaluate drive at.

		description:
			function which diagonalizes hamiltonian using dense methods solves for eigen values 
			and eigen vectors. uses wrapped lapack functions which are contained in module py_lapack
		"""

		
		if _np.array(time).ndim > 0:
			raise TypeError('expecting scalar argument for time')

		if self.Ns <= 0:
			return _np.asarray([])

		H_dense = self.todense(time=time)
		eigvalsh_args["overwrite_a"] = True
		E = _la.eigvalsh(H_dense,**eigvalsh_args)
		return E


	def __LO(self,time,rho):
		rho = rho.reshape((self.Ns,self.Ns))

		rho_comm = self._static.dot(rho)
		rho_comm -= (self._static.T.dot(rho.T)).T
		for func,Hd in iteritems(self._dynamic):
			ft = func(time)
			rho_comm += ft*Hd.dot(rho)	
			rho_comm -= ft*(Hd.T.dot(rho.T)).T

		rho_comm *= -1j
		return rho_comm.reshape((-1,))


	def __multi_SO_real(self,time,V):
		"""
		args:
			V, the vector to multiple with
			time, the time to evalute drive at.

		description:
			This function is what get's passed into the ode solver. This is the real time Schrodinger operator -i*H(t)*|V >
			This function is designed for real hamiltonians and increases the speed of integration compared to __SO
		
		u_dot + iv_dot = -iH(u + iv)
		u_dot = Hv
		v_dot = -Hu
		"""
		V = V.reshape((2*self._Ns,-1))
		V_dot = _np.zeros_like(V)
		V_dot[:self._Ns,:] = self._static.dot(V[self._Ns:,:])
		V_dot[self._Ns:,:] = -self._static.dot(V[:self._Ns,:])
		for func,Hd in iteritems(self._dynamic):
			V_dot[:self._Ns,:] += func(time)*Hd.dot(V[self._Ns:,:])
			V_dot[self._Ns:,:] += -func(time)*Hd.dot(V[:self._Ns,:])

		return V_dot.reshape((-1,))


	def __multi_SO(self,time,V):
		"""
		args:
			V, the vector to multiple with
			time, the time to evalute drive at.

		description:
			This function is what get's passed into the ode solver. This is the real time Schrodinger operator -i*H(t)*|V >
		"""
		V = V.reshape((self.Ns,-1))
		V_dot = self._static.dot(V)	
		for func,Hd in iteritems(self._dynamic):
			V_dot += func(time)*(Hd.dot(V))

		return -1j*V_dot.reshape((-1,))


	def __multi_ISO(self,time,V):
		"""
		args:
			V, the vector to multiple with
			time, the time to evalute drive at.

		description:
			This function is what get's passed into the ode solver. This is the Imaginary time Schrodinger operator -H(t)*|V >
		"""
		V = V.reshape((self._Ns,-1))
		V_dot = -self._static.dot(V)	
		for func,Hd in iteritems(self._dynamic):
			V_dot -= func(time)*(Hd.dot(V))

		return V_dot.reshape((-1,))



	def __SO_real(self,time,V):
		"""
		args:
			V, the vector to multiple with
			time, the time to evalute drive at.

		description:
			This function is what get's passed into the ode solver. This is the real time Schrodinger operator -i*H(t)*|V >
			This function is designed for real hamiltonians and increases the speed of integration compared to __SO
		
		u_dot + iv_dot = -iH(u + iv)
		u_dot = Hv
		v_dot = -Hu
		"""
		V_dot = _np.zeros_like(V)
		V_dot[:self._Ns] = self._static.dot(V[self._Ns:])
		V_dot[self._Ns:] = -self._static.dot(V[:self._Ns])
		for func,Hd in iteritems(self._dynamic):
			V_dot[:self._Ns] += func(time)*Hd.dot(V[self._Ns:])
			V_dot[self._Ns:] += -func(time)*Hd.dot(V[:self._Ns])

		return V_dot


	def __SO(self,time,V):
		"""
		args:
			V, the vector to multiple with
			time, the time to evalute drive at.

		description:
			This function is what get's passed into the ode solver. This is the real time Schrodinger operator -i*H(t)*|V >
		"""
		V_dot = self._static.dot(V)	
		for func,Hd in iteritems(self._dynamic):
			V_dot += func(time)*(Hd.dot(V))

		return -1j*V_dot

	def __ISO(self,time,V):
		"""
		args:
			V, the vector to multiple with
			time, the time to evalute drive at.

		description:
			This function is what get's passed into the ode solver. This is the Imaginary time Schrodinger operator -H(t)*|V >
		"""

		V_dot = -self._static.dot(V)	
		for func,Hd in iteritems(self._dynamic):
			V_dot -= func(time)*(Hd.dot(V))

		return V_dot



	def evolve(self,v0,t0,times,eom="SE",solver_name="dop853",H_real=False,verbose=False,iterate=False,imag_time=False,**solver_args):
		from scipy.integrate import complex_ode
		from scipy.integrate import ode

		shape0 = v0.shape

		if eom == "SE":
			n = _np.linalg.norm(v0,axis=0) # needed for imaginary time to preserve the proper norm of the state. 

			
			if v0.ndim > 2:
				raise ValueError("v0 must have ndim <= 2")

			if v0.shape[0] != self.Ns:
				raise ValueError("v0 must have {0} elements".format(self.Ns))

			if imag_time:
				v0 = v0.astype(self.dtype)
				if _np.iscomplexobj(v0):
					if v0.ndim == 1:
						solver = complex_ode(self.__ISO)
					else:
						solver = complex_ode(self.__multi_ISO)
				else:
					if v0.ndim == 1:
						solver = ode(self.__ISO)
					else:
						solver = ode(self.__multi_ISO)
			else:
				if H_real:
					v1 = v0
					v0 = _np.zeros((2*self._Ns,)+v0.shape[1:],dtype=v1.real.dtype)
					v0[:self._Ns] = v1.real
					v0[self._Ns:] = v1.imag
					if v0.ndim == 1:
						solver = ode(self.__SO_real)
					else:
						solver = ode(self.__multi_SO_real)
				else:
					v0 = v0.astype(_np.complex128)
					if v0.ndim == 1:
						solver = complex_ode(self.__SO)
					else:
						solver = complex_ode(self.__multi_SO)

		elif eom == "LvNE":
			n = 1.0
			if v0.ndim != 2:
				raise ValueError("v0 must have ndim = 2")

			if v0.shape != self._shape:
				raise ValueError("v0 must be same shape as Hamiltonian")

			if imag_time:
				raise NotImplementedError("imaginary time not implemented for Liouville-von Neumann dynamics")
			else:
				if H_real:
					raise NotImplementedError("H_real not implemented for Liouville-von Neumann dynamics")
				else:
					solver = complex_ode(self.__LO)
		else:
			raise ValueError("'{} equation' not recognized, must be 'SE' or 'LvNE'".format(equation))


		if _np.iscomplexobj(times):
			raise ValueError("times must be real number(s).")

		if solver_name in ["dop853","dopri5"]:
			if solver_args.get("nsteps") is None:
				solver_args["nsteps"] = _np.iinfo(_np.int32).max
			if solver_args.get("rtol") is None:
				solver_args["rtol"] = 1E-9
			if solver_args.get("atol") is None:
				solver_args["atol"] = 1E-9

				
		solver.set_integrator(solver_name,**solver_args)
		solver.set_initial_value(v0.ravel(), t0)

		if _np.isscalar(times):
			return self._evolve_scalar(solver,v0,t0,times,imag_time,H_real,n,shape0)
		else:
			if iterate:
				return self._evolve_iter(solver,v0,t0,times,verbose,imag_time,H_real,n,shape0)
			else:
				return self._evolve_list(solver,v0,t0,times,verbose,imag_time,H_real,n,shape0)

			
	def _evolve_scalar(self,solver,v0,t0,time,imag_time,H_real,n,shape0):
		from numpy.linalg import norm
		N_ele = v0.size//2

		if time == t0:
			if H_real:
				_np.squeeze((v0[:N_ele] + 1j*v0[N_ele:]).reshape(shape0))
			else:
				return _np.squeeze(v0.reshape(shape0))

		solver.integrate(time)
		if solver.successful():
			if imag_time: solver._y /= (norm(solver._y)/n)
			if H_real:
				return _np.squeeze((solver.y[:N_ele] + 1j*solver.y[N_ele:]).reshape(shape0))
			else:
				return _np.squeeze(solver.y.reshape(shape0))
		else:
			raise RuntimeError("failed to evolve to time {0}, nsteps might be too small".format(time))	



	def _evolve_list(self,solver,v0,t0,times,verbose,imag_time,H_real,n,shape0):
		from numpy.linalg import norm

		N_ele = v0.size//2
		v = _np.empty(shape0+(len(times),),dtype=_np.complex128)
		
		for i,t in enumerate(times):
			if t == t0:
				if verbose: print("evolved to time {0}, norm of state {1}".format(t,_np.linalg.norm(solver.y)))
				if H_real:
					v[...,i] = _np.squeeze((v0[:N_ele] + 1j*v0[N_ele:]).reshape(shape0))
				else:
					v[...,i] = _np.squeeze(v0.reshape(shape0))
				continue

			solver.integrate(t)
			if solver.successful():
				if verbose: print("evolved to time {0}, norm of state {1}".format(t,_np.linalg.norm(solver.y)))
				if imag_time: solver._y /= (norm(solver._y)/n)
				if H_real:
					v[...,i] = _np.squeeze((solver.y[:N_ele] + 1j*solver.y[N_ele:]).reshape(shape0))
				else:
					v[...,i] = _np.squeeze(solver.y.reshape(shape0))
			else:
				raise RuntimeError("failed to evolve to time {0}, nsteps might be too small".format(t))
				
		return _np.squeeze(v)



	def _evolve_iter(self,solver,v0,t0,times,verbose,imag_time,H_real,n,shape0):
		from numpy.linalg import norm
		N_ele = v0.size//2

		for i,t in enumerate(times):
			if t == t0:
				if verbose: print("evolved to time {0}, norm of state {1}".format(t,_np.linalg.norm(solver.y)))
				if H_real:
					yield _np.squeeze((v0[:N_ele] + 1j*v0[N_ele:]).reshape(shape0))
				else:
					yield _np.squeeze(v0.reshape(shape0))
				continue
				

			solver.integrate(t)
			if solver.successful():
				if verbose: print("evolved to time {0}, norm of state {1}".format(t,_np.linalg.norm(solver.y)))
				if imag_time: solver._y /= (norm(solver.y)/n)
				if H_real:
					yield _np.squeeze((solver.y[:N_ele] + 1j*solver.y[N_ele:]).reshape(shape0))
				else:
					yield _np.squeeze(solver.y.reshape(shape0))
			else:
				raise RuntimeError("failed to evolve to time {0}, nsteps might be too small".format(t))
		

	def aslinearoperator(self,time=0):
		time = _np.array(time)
		if time.ndim > 0:
			raise ValueError("time must be scalar!")
		matvec = functools.partial(_hamiltonian_dot,self,time)
		rmatvec = functools.partial(_hamiltonian_dot,self.H,time)
		return _sla.LinearOperator(self.get_shape,matvec,rmatvec=rmatvec,matmat=matvec,dtype=self._dtype)		


	def tocsr(self,time=0):
		"""
		args:
			time=0, the time to evalute drive at.

		description:
			this function simply returns a copy of the Hamiltonian as a csr_matrix evaluated at the desired time.
		"""
		if self.Ns <= 0:
			return _sp.csr_matrix(_np.asarray([[]]))
		if _np.array(time).ndim > 0:
			raise TypeError('expecting scalar argument for time')


		H = _sp.csr_matrix(self._static)

		for func,Hd in iteritems(self._dynamic):
			Hd = _sp.csr_matrix(Hd)
			try:
				H += Hd * func(time)
			except:
				H = H + Hd * func(time)


		return H

	def tocsc(self,time=0):
		"""
		args:
			time=0, the time to evalute drive at.

		description:
			this function simply returns a copy of the Hamiltonian as a csr_matrix evaluated at the desired time.
		"""
		if self.Ns <= 0:
			return _sp.csc_matrix(_np.asarray([[]]))
		if _np.array(time).ndim > 0:
			raise TypeError('expecting scalar argument for time')

		H = _sp.csc_matrix(self._static)
		for func,Hd in iteritems(self._dynamic):
			Hd = _sp.csc_matrix(Hd)
			try:
				H += Hd * func(time)
			except:
				H = H + Hd * func(time)


		return H


	
	def todense(self,time=0,order=None, out=None):
		"""
		args:
			time=0, the time to evalute drive at.

		description:
			this function simply returns a copy of the Hamiltonian as a dense matrix evaluated at the desired time.
			This function can overflow memory if not careful.
		"""

		if out is None:
			out = _np.zeros(self._shape,dtype=self.dtype)
			out = _np.asmatrix(out)

		if _sp.issparse(self._static):
			self._static.todense(order=order,out=out)
		else:
			out[:] = self._static[:]

		for func,Hd in iteritems(self._dynamic):
			out += Hd * func(time)
		
		return out


	def toarray(self,time=0,order=None, out=None):
		"""
		args:
			time=0, the time to evalute drive at.

		description:
			this function simply returns a copy of the Hamiltonian as a dense matrix evaluated at the desired time.
			This function can overflow memory if not careful.
		"""

		if out is None:
			out = _np.zeros(self._shape,dtype=self.dtype)

		if _sp.issparse(self._static):
			self._static.toarray(order=order,out=out)
		else:
			out[:] = self._static[:]

		for func,Hd in iteritems(self._dynamic):
			out += Hd * func(time)
		
		return out



	def as_dense_format(self,copy=False):
		if copy:
			new = _deepcopy(self)
		else:
			new = _shallowcopy(self)


		if _sp.issparse(new._static):
			new._static = new._static.todense()
		else:
			new._static = _np.asarray(new._static)


		for func in new._dynamic:
			if _sp.issparse(new._dynamic[func]):
				new._dynamic[func] = new._dynamic[func].toarray()
			else:
				new._dynamic[func] = _np.asarray(new._dynamic[func],copy=copy)

		return new


	def as_sparse_format(self,fmt,copy=False):
		if type(fmt) is not str:
			raise ValueError("Expecting string for 'fmt'")

		if fmt not in ["csr","csc","dia","bsr"]:
			raise ValueError("'{0}' is not a valid sparse format or does not support arithmetic.".format(fmt))

		if copy:
			new = _deepcopy(self)
		else:
			new = _shallowcopy(self)

		sparse_constuctor = getattr(_sp,fmt+"_matrix")

		new._static = sparse_constuctor(new._static)
		new._dynamic = list(new._dynamic)
		new._dynamic = {func:sparse_constructor(Hd) for func,Hd in iteritems(new._dynamic)}

		return new


	def conj(self):
		new = _shallowcopy(self)

		new._static = new._static.conj()
		new._dynamic = {func.conj():Hd.conj() for func,Hd in iteritems(new._dynamic)}

		# new._dynamic = list(new._dynamic)
		# n = len(self._dynamic)
		# for i in range(n):
		# 	new._dynamic[i] = list(new._dynamic[i])
		# 	new._dynamic[i][0] = new._dynamic[i][0].conj()
		# 	new._dynamic[i] = tuple(new._dynamic[i])

		# new._dynamic = tuple(new._dynamic)

		return new

	def diagonal(self,time=0):
		if self.Ns <= 0:
			return 0
		if _np.array(time).ndim > 0:
			raise TypeError('expecting scalar argument for time')

		diagonal = self._static.diagonal()
		for func,Hd in iteritems(self._dynamic):
			diagonal += Hd.diagonal() * func(time)

		return diagonal

	def trace(self,time=0):
		if self.Ns <= 0:
			return 0
		if _np.array(time).ndim > 0:
			raise TypeError('expecting scalar argument for time')

		trace = self._static.diagonal().sum()
		for func,Hd in iteritems(self._dynamic):
			trace += Hd.diagonal().sum() * func(time)

		return trace
 		

	def getH(self,copy=False):
		return self.conj().transpose(copy=copy)


	def transpose(self,copy=False):
		if copy:
			new = _deepcopy(self)
		else:
			new = _shallowcopy(self)

		new._static = new._static.T
		new._dynamic = {func:Hd.T for func,Hd in iteritems(new._dynamic)}

		return new



	def astype(self,dtype):
		if dtype not in supported_dtypes:
			raise TypeError('hamiltonian does not support type: '+str(dtype))

		new = _shallowcopy(self)

		new._dtype = dtype
		new._static = new._static.astype(dtype)
		new._dynamic = {func:Hd.astype(dtype) for func,Hd in iteritems(new._dynamic)}

		return new
		




	def copy(self):
		dynamic = [[M,func] for func,M in iteritems(self.dynamic)]
		return hamiltonian([self.static],dynamic,basis=self.basis,dtype=self._dtype,copy=True)


	###################
	# special methods #
	###################


	def __getitem__(self,key):
		if len(key) != 3:
			raise IndexError("invalid number of indices, hamiltonian must be indexed with three indices [time,row,col].")
		try:
			times = iter(key[0])
			iterate=True
		except TypeError:
			time = key[0]
			iterate=False

		key = tuple(key[1:])
		if iterate:
			ME = []
			if self.is_dense:
				for t in times:
					ME.append(self.todense(time=t)[key])
			else:
				for t in times:
					ME.append(self.tocsr(time=t)[key])
				
			ME = tuple(ME)
		else:
			ME = self.tocsr(time=time)[key]

		return ME
			
		


	def __str__(self):
		string = "static mat: \n{0}\n\n\ndynamic:\n".format(self._static.__str__())
		for i,(func,Hd) in enumerate(iteritems(self._dynamic)):
			h_str = Hd.__str__()
			func_str = func.__str__()
			
			string += ("{0}) func: {2}, mat: \n{1} \n".format(i,h_str,func_str))

		return string
		

	def __repr__(self):
		matrix_format={"csr":"Compressed Sparse Row",
						"csc":"Compressed Sparse Column",
						"dia":"DIAgonal",
						"bsr":"Block Sparse Row"
						}
		if self.is_dense:
			return "<{0}x{1} qspin dense hamiltonian of type '{2}'>".format(*(self._shape[0],self._shape[1],self._dtype))
		else:
			fmt = matrix_format[self._static.getformat()]
			return "<{0}x{1} qspin sprase hamiltonian of type '{2}' stored in {3} format>".format(*(self._shape[0],self._shape[1],self._dtype,fmt))


	def __neg__(self): # -self
		new = _shallowcopy(self)

		new._static = -new._static

		new._dynamic = {func:-Hd for func,Hd in iteritems(new._dynamic)}
		# new._dynamic = list(new._dynamic)
		# n = len(new._dynamic)
		# for i in range(n):
		# 	new._dynamic[i][-1] = -new._dynamic[i][-1]

		# new._dynamic = tuple(new._dynamic)
		
		return new


	def __call__(self,time):
		if self.is_dense:
			return self.toarray(time)
		else:
			return self.tocsr(time)


	##################################
	# symbolic arithmetic operations #
	# currently only have +,-,* like #
	# operators implimented.		 #
	##################################

	def __pow__(self,power):
		if type(power) is not int:
			raise TypeError("hamiltonian can only be raised to integer power.")

		return reduce(mul,(self for i in range(power)))



	def __mul__(self,other): # self * other
		if ishamiltonian(other):			
			return self._mul_hamiltonian(other)

		elif _sp.issparse(other):
			self._mat_checks(other,casting="unsafe")
			return self._mul_sparse(other)

		elif _np.isscalar(other):
			return self._mul_scalar(other)

		elif other.__class__ == _np.ndarray:
			self._mat_checks(other,casting="unsafe")
			return self._mul_dense(other)

		elif other.__class__ == _np.matrix:
			self._mat_checks(other,casting="unsafe")
			return self._mul_dense(other)

		else:
			other = _np.asanyarray(other)
			self._mat_checks(other,casting="unsafe")
			return self._mul_dense(other)






	def __rmul__(self,other): # other * self
		if ishamiltonian(other):
			self._mat_checks(other,casting="unsafe")
			return self._rmul_hamiltonian(other)

		elif _sp.issparse(other):
			self._mat_checks(other,casting="unsafe")
			return self._rmul_sparse(other)

		elif _np.isscalar(other):

			return self._mul_scalar(other)

		elif other.__class__ == _np.ndarray:
			self._mat_checks(other,casting="unsafe")
			return self._rmul_dense(other)

		elif other.__class__ == _np.matrix:
			self._mat_checks(other,casting="unsafe")
			return self._rmul_dense(other)

		else:
			other = _np.asanyarray(other)
			self._mat_checks(other,casting="unsafe")
			return self._rmul_dense(other)







	def __imul__(self,other): # self *= other
		if ishamiltonian(other):
			self._mat_checks(other)
			return self._imul_hamiltonian(other)

		
		elif _sp.issparse(other):
			self._mat_checks(other)	
			return self._imul_sparse(other)

		elif _np.isscalar(other):
			return self._imul_scalar(other)

		elif other.__class__ == _np.ndarray:
			self._mat_checks(other)	
			return self._imul_dense(other)

		elif other.__class__ == _np.matrix:
			self._mat_checks(other)	
			return self._imul_dense(other)

		else:
			other = _np.asanyarray(other)
			self._mat_checks(other)	
			return self._imul_dense(other)


	def __truediv__(self,other):
		return self.__div__(other)

	def __div__(self,other): # self / other
		if ishamiltonian(other):			
			return NotImplemented

		elif _sp.issparse(other):
			return NotImplemented

		elif _np.isscalar(other):
			return self._mul_scalar(1.0/other)

		elif other.__class__ == _np.ndarray:
			return NotImplemented

		elif other.__class__ == _np.matrix:
			return NotImplemented

		else:
			return NotImplemented





	def __rdiv__(self,other): # other / self
		return NotImplemented


	def __idiv__(self,other): # self *= other
		if ishamiltonian(other):
			return NotImplemented
		
		elif _sp.issparse(other):
			return NotImplemented

		elif _np.isscalar(other):
			return self._imul_scalar(1.0/other)

		elif other.__class__ == _np.ndarray:
			return NotImplemented

		elif other.__class__ == _np.matrix:
			return NotImplemented

		else:
			return NotImplemented




	def __add__(self,other): # self + other
		if ishamiltonian(other):
			self._mat_checks(other,casting="unsafe")
			return self._add_hamiltonian(other)

		elif _sp.issparse(other):
			self._mat_checks(other,casting="unsafe")
			return self._add_sparse(other)
			
		elif _np.isscalar(other):
			if other==0.0:
				return self.copy()
			else:
				raise NotImplementedError('hamiltonian does not support addition by nonzero scalar')

		elif other.__class__ == _np.ndarray:
			self._mat_checks(other,casting="unsafe")
			return self._add_dense(other)

		elif other.__class__ == _np.matrix:
			self._mat_checks(other,casting="unsafe")
			return self._add_dense(other)

		else:
			other = _np.asanyarray(other)
			self._mat_checks(other,casting="unsafe")
			return self._add_dense(other)





	def __radd__(self,other): # other + self
		return self.__add__(other)






	def __iadd__(self,other): # self += other
		if ishamiltonian(other):
			self._mat_checks(other)
			return self._iadd_hamiltonian(other)

		elif _sp.issparse(other):
			self._mat_checks(other)	
			return self._iadd_sparse(other)

		elif _np.isscalar(other):
			if other==0.0:
				return self.copy()
			else:
				raise NotImplementedError('hamiltonian does not support addition by nonzero scalar')

		elif other.__class__ == _np.ndarray:
			self._mat_checks(other)	
			return self._iadd_dense(other)

		else:
			other = _np.asanyarray(other)
			self._mat_checks(other)				
			return self._iadd_dense(other)






	def __sub__(self,other): # self - other
		if ishamiltonian(other):
			self._mat_checks(other,casting="unsafe")
			return self._sub_hamiltonian(other)

		elif _sp.issparse(other):
			self._mat_checks(other,casting="unsafe")
			return self._sub_sparse(other)

		elif _np.isscalar(other):
			if other==0.0:
				return self.copy()
			else:
				raise NotImplementedError('hamiltonian does not support subtraction by nonzero scalar')

		elif other.__class__ == _np.ndarray:
			self._mat_checks(other,casting="unsafe")
			return self._sub_dense(other)

		else:
			other = _np.asanyarray(other)
			self._mat_checks(other,casting="unsafe")
			return self._sub_dense(other)



	def __rsub__(self,other): # other - self
		# NOTE: because we use signed types this is possble
		return self.__sub__(other).__neg__()




	def __isub__(self,other): # self -= other
		if ishamiltonian(other):
			self._mat_checks(other)
			return self._isub_hamiltonian(other)

		elif _sp.issparse(other):
			self._mat_checks(other)			
			return self._isub_sparse(other)

		elif _np.isscalar(other):
			if other==0.0:
				return self.copy()
			else:
				raise NotImplementedError('hamiltonian does not support subtraction by nonzero scalar')

		elif other.__class__ == _np.ndarray:
			self._mat_checks(other)	
			return self._isub_dense(other)

		else:
			other = _np.asanyarray(other)
			self._mat_checks(other)	
			return self._sub_dense(other)

	##########################################################################################	
	##########################################################################################
	# below all of the arithmetic functions are implimented for various combination of types #
	##########################################################################################
	##########################################################################################


	# checks
	def _mat_checks(self,other,casting="same_kind"):
		try:
			if other.shape != self._shape: # only accepts square matricies 
				raise ValueError('shapes do not match')
			if not _np.can_cast(other.dtype,self._dtype,casting=casting):
				raise ValueError('cannot cast types')
		except AttributeError:
			if other._shape != self._shape: # only accepts square matricies 
				raise ValueError('shapes do not match')
			if not _np.can_cast(other.dtype,self._dtype,casting=casting):
				raise ValueError('cannot cast types')			



	def _add_hamiltonian(self,other): 
		dtype = _np.result_type(self._dtype, other.dtype)
		new=self.astype(dtype)

		new._is_dense = new._is_dense or other._is_dense

		try:
			new._static += other._static 
		except NotImplementedError:
			new._static = new._static + other._static 

		try:
			new._static.sum_duplicates()
			new._static.eliminate_zeros()
		except: pass

		if _check_almost_zero(new._static):
			new._static = _sp.csr_matrix(new._shape,dtype=new._dtype)

		for func,Hd in iteritems(other._dynamic):
			if func in new._dynamic:
				try:
					new._dynamic[func] += Hd
				except NotImplementedError:
					new._dynamic[func] = new._dynamic[func] + Hd

				try:
					new._dynamic[func].sum_duplicates()
					new._dynamic[func].eliminate_zeros()
				except: pass

				if _check_almost_zero(new._dynamic[func]):
					new._dynamic.pop(func)
			else:
				new._dynamic[func] = Hd

		new.check_is_dense()
		return new




	def _iadd_hamiltonian(self,other):
		self._is_dense = self._is_dense or other._is_dense

		try:
			self._static += other._static 
		except NotImplementedError:
			self._static = self._static + other._static 

		try:
			self._static.sum_duplicates()
			self._static.eliminate_zeros()
		except: pass

		if _check_almost_zero(self._static):
			self._static = _sp.csr_matrix(self._shape,dtype=self._dtype)

		for func,Hd in iteritems(other._dynamic):
			if func in self._dynamic:
				try:
					self._dynamic[func] += Hd
				except NotImplementedError:
					self._dynamic[func] = self._dynamic[func] + Hd

				try:
					self._dynamic[func].sum_duplicates()
					self._dynamic[func].eliminate_zeros()
				except: pass

				if _check_almost_zero(self._dynamic[func]):
					self._dynamic.pop(func)

			else:
				self._dynamic[func] = Hd

		self.check_is_dense()
		return _shallowcopy(self)




	def _sub_hamiltonian(self,other): 
		dtype = _np.result_type(self._dtype, other.dtype)
		new=self.astype(dtype)

		new._is_dense = new._is_dense or other._is_dense

		try:
			new._static -= other._static 
		except NotImplementedError:
			new._static = new._static - other._static 

		try:
			new._static.sum_duplicates()
			new._static.eliminate_zeros()
		except: pass


		if _check_almost_zero(new._static):
			new._static = _sp.csr_matrix(new._shape,dtype=new._dtype)


		for func,Hd in iteritems(other._dynamic):
			if func in new._dynamic:
				try:
					new._dynamic[func] -= Hd
				except NotImplementedError:
					new._dynamic[func] = new._dynamic[func] - Hd

				try:
					new._dynamic[func].sum_duplicates()
					new._dynamic[func].eliminate_zeros()
				except: pass


				if _check_almost_zero(new._dynamic[func]):
					new._dynamic.pop(func)

			else:
				new._dynamic[func] = -Hd		

		new.check_is_dense()
		return new





	def _isub_hamiltonian(self,other): 
		self._is_dense = self._is_dense or other._is_dense

		try:
			self._static -= other._static 
		except NotImplementedError:
			self._static = self._static - other._static 

		try:
			self._static.sum_duplicates()
			self._static.eliminate_zeros()
		except: pass

		if _check_almost_zero(self._static):
			self._static = _sp.csr_matrix(self._shape,dtype=self._dtype)



		for func,Hd in iteritems(other._dynamic):
			if func in self._dynamic:
				try:
					self._dynamic[func] -= Hd
				except NotImplementedError:
					self._dynamic[func] = new._dynamic[func] - Hd

				try:
					self._dynamic[func].sum_duplicates()
					self._dynamic[func].eliminate_zeros()
				except: pass

				if _check_almost_zero(new._dynamic[func]):
					self._dynamic.pop(func)

			else:
				self._dynamic[func] = -Hd

	
		self.check_is_dense()
		return _shallowcopy(self)


	def _mul_hamiltonian(self,other): # self * other
		if self.dynamic and other.dynamic:
			new = self.copy()
			return new.__imul__(other)
		elif self.dynamic:
			return self.__mul__(other.static)
		elif other.dynamic:
			return other.__rmul__(self.static)
		else:
			return self.__mul__(other.static)


	def _rmul_hamiltonian(self,other): # other * self
		if self.dynamic and other.dynamic:
			new = other.copy()
			return (new.T.__imul__(self.T)).T #lazy implementation
		elif self.dynamic:
			return self.__rmul__(other.static)
		elif other.dynamic:
			return other.__mul__(self.static)
		else:
			return self.__rmul__(other.static)

	def _imul_hamiltonian(self,other): # self *= other
		if self.dynamic and other.dynamic:
			self._is_dense = self._is_dense or other._is_dense

			new_dynamic_ops = {}
			# create new dynamic operators coming from
			# self.static * other
			for func,Hd in iteritems(other._dynamic):
				if _sp.issparse(self.static):
					Hmul = self.static.dot(Hd)
				elif _sp.issparse(Hd):
					Hmul = self.static * Hd
				else:
					Hmul = _np.matmul(self.static,Hd)

				if not _check_almost_zero(Hmul):
					new_dynamic_ops[func] = Hmul



			for func1,H1 in iteritems(self._dynamic):
				for func2,H2 in iteritems(other._dynamic):

					if _sp.issparse(H1):
						H12 = H1.dot(H2)
					elif _sp.issparse(H2):
						H12 = H1 * H2
					else:
						H12 = _np.matmul(H1,H2)

					func12 = func1 * func2

					if func12 in new_dynamic_ops:
						try:
							new_dynamic_ops[func12] += H12
						except NotImplementedError:
							new_dynamic_ops[func12] = new_dynamic_ops[func12] + H12

						try:
							new_dynamic_ops[func12].sum_duplicates()
							new_dynamic_ops[func12].eliminate_zeros()
						except: pass

						if _check_almost_zero(new_dynamic_ops[func12]):
							new_dynamic_ops.pop(func12)
					else:
						if not _check_almost_zero(H12):
							new_dynamic_ops[func12] = H12


			self._dynamic = new_dynamic_ops
			return _shallowcopy(self)
		elif self.dynamic:
			return self.__imul__(other.static)
		elif other.dynamic:
			return (other.T.__imul__(self.static.T)).T
		else:
			return self.__imul__(other.static)





	#####################
	# sparse operations #
	#####################


	def _add_sparse(self,other):

		dtype = _np.result_type(self._dtype, other.dtype)
		new=self.astype(dtype)

		try:
			new._static += other
		except NotImplementedError:
			new._static = new._static + other

		try:
			new._static.sum_duplicates()
			new._static.eliminate_zeros()
		except: pass

		if _check_almost_zero(new._static):
			new._static = _sp.csr_matrix(new._shape,dtype=new._dtype)

		new.check_is_dense()
		return new	


	def _iadd_sparse(self,other):

		try:
			self._static += other
		except NotImplementedError:
			self._static = self._static + other

		try:
			self._static.sum_duplicates()
			self._static.eliminate_zeros()
		except: pass

		if _check_almost_zero(self._static):
			self._static = _sp.csr_matrix(self._shape,dtype=self._dtype)

		self.check_is_dense()
		return self	
	



	def _sub_sparse(self,other):

		dtype = _np.result_type(self._dtype, other.dtype)
		new=self.astype(dtype)

		try:
			new._static -= other
		except NotImplementedError:
			new._static = new._static - other

		try:
			new._static.sum_duplicates()
			new._static.eliminate_zeros()
		except: pass

		if _check_almost_zero(new._static):
			new._static = _sp.csr_matrix(new._shape,dtype=new._dtype)

		new.check_is_dense()
		return new	


	def _isub_sparse(self,other):

		try:
			self._static -= other
		except NotImplementedError:
			self._static = self._static - other

		try:
			self._static.sum_duplicates()
			self._static.eliminate_zeros()
		except: pass

		if _check_almost_zero(self._static):
			self._static = _sp.csr_matrix(self._shape,dtype=self._dtype)

		self.check_is_dense()
		return self




	def _mul_sparse(self,other):

		dtype = _np.result_type(self._dtype, other.dtype)
		new=self.astype(dtype)

		new._static = new._static * other

		try:
			new._static.sum_duplicates()
			new._static.eliminate_zeros()
		except: pass


		if _check_almost_zero(new._static):
			new._static = _sp.csr_matrix(new._shape,dtype=new._dtype)


		for func in list(new._dynamic):
			new._dynamic[func] = new._dynamic[func] * other

			try:
				new._dynamic[func].sum_duplicates()
				new._dynamic[func].eliminate_zeros()
			except: pass

			if _check_almost_zero(new._dynamic[func]):
				new._dynamic.pop(func)

		new.check_is_dense()
		return new





	def _rmul_sparse(self,other):
		# Auxellery function to calculate the right-side multipication with another sparse matrix.

		# find resultant type from product
		dtype = _np.result_type(self._dtype, other.dtype)
		# create a copy of the hamiltonian object with the previous dtype
		new=self.astype(dtype)

		# proform multiplication on all matricies of the new hamiltonian object.

		new._static = other * new._static

		try:
			new._static.sum_duplicates()
			new._static.eliminate_zeros()
		except: pass

		if _check_almost_zero(new._static):
			new._static = _sp.csr_matrix(new._shape,dtype=new._dtype)

		for func in list(new._dynamic):
			new._dynamic[func] = other.dot(new._dynamic[func])

			try:
				new._dynamic[func].sum_duplicates()
				new._dynamic[func].eliminate_zeros()
			except: pass

			if _check_almost_zero(new._dynamic[func]):
				new._dynamic.pop(func)


		new.check_is_dense()		
		return new




	def _imul_sparse(self,other):


		self._static =self._static * other

		try:	
			self._static.sum_duplicates()
			self._static.eliminate_zeros()
		except: pass

		if _check_almost_zero(self._static):
			self._static = _sp.csr_matrix(self._shape,dtype=self._dtype)


		for func in list(self._dynamic):
			self._dynamic[func] = other.dot(self._dynamic[func])

			try:
				self._dynamic[func].sum_duplicates()
				self._dynamic[func].eliminate_zeros()
			except: pass

			if _check_almost_zero(self._dynamic[func]):
				self._dynamic.pop(func)

		self.check_is_dense()
		return _shallowcopy(self)




	#####################
	# scalar operations #
	#####################



	def _mul_scalar(self,other):
		dtype = _np.result_type(self._dtype, other)
		new=self.astype(dtype)


		new=self.copy()
		try:
			new._static *= other
		except NotImplementedError:
			new._static = new._static * other

		if _check_almost_zero(new._static):
			new._static = _sp.csr_matrix(new._shape,dtype=new._dtype)

		for func in list(new._dynamic):
			try:
				new._dynamic[func] *= other
			except NotImplementedError:
				new._dynamic[func] = new._dynamic[func] * other

			try:
				new._dynamic[func].sum_duplicates()
				new._dynamic[func].eliminate_zeros()
			except: pass

			if _check_almost_zero(new._dynamic[func]):
				new._dynamic.pop(func)

		new.check_is_dense()
		return new







	def _imul_scalar(self,other):
		if not _np.can_cast(other,self._dtype,casting="same_kind"):
			raise TypeError("cannot cast types")

		try:
			self._static *= other
		except NotImplementedError:
			self._static = self._static * other

		if _check_almost_zero(self._static):
			self._static = _sp.csr_matrix(self._shape,dtype=self._dtype)

		for func in list(self._dynamic):
			try:
				self._dynamic[func] *= other
			except NotImplementedError:
				self._dynamic[func] = self._dynamic[func] * other

			try:
				self._dynamic[func].sum_duplicates()
				self._dynamic[func].eliminate_zeros()
			except: pass

			if _check_almost_zero(self._dynamic[func]):
				self._dynamic.pop(func)

		self.check_is_dense()
		return _shallowcopy(self)



	####################
	# dense operations #
	####################


	def _add_dense(self,other):

		dtype = _np.result_type(self._dtype, other.dtype)

		if dtype not in supported_dtypes:
			return NotImplemented

		new=self.astype(dtype)

		if not self._is_dense:
			self._is_dense = True
			warnings.warn("Mixing dense objects will cast internal matrices to dense.",HamiltonianEfficiencyWarning,stacklevel=3)

		try:
			new._static += other
		except:
			new._static = new._static + other

		if _check_almost_zero(new._static):
			new._static = _sp.csr_matrix(new._shape,dtype=new._dtype)

		new.check_is_dense()
		return new



	def _iadd_dense(self,other):

		if not self._is_dense:
			self._is_dense = True
			warnings.warn("Mixing dense objects will cast internal matrices to dense.",HamiltonianEfficiencyWarning,stacklevel=3)


		try: 
			self._static += other
		except:
			self._static = new._static + other

		if _check_almost_zero(self._static):
			self._static = _sp.csr_matrix(self._shape,dtype=self._dtype)

		self.check_is_dense()

		return _shallowcopy(self)




	def _sub_dense(self,other):

		dtype = _np.result_type(self._dtype, other.dtype)

		if dtype not in supported_dtypes:
			return NotImplemented

		new=self.astype(dtype)


		if not self._is_dense:
			self._is_dense = True
			warnings.warn("Mixing dense objects will cast internal matrices to dense.",HamiltonianEfficiencyWarning,stacklevel=3)

		try:
			new._static -= other
		except:
			new._static = new._static - other

		if _check_almost_zero(new._static):
			new._static = _sp.csr_matrix(new._shape,dtype=new._dtype)

		new.check_is_dense()

		return new



	def _isub_dense(self,other):

		if not self._is_dense:
			self._is_dense = True
			warnings.warn("Mixing dense objects will cast internal matrices to dense.",HamiltonianEfficiencyWarning,stacklevel=3)


		try:
			self._static -= other
		except:
			self._static = self._static - other

		if _check_almost_zero(new._static):
			new._static = _sp.csr_matrix(new._shape,dtype=new._dtype)

		self.check_is_dense()
		return _shallowcopy(self)


	def _mul_dense(self,other):

		dtype = _np.result_type(self._dtype, other.dtype)

		if dtype not in supported_dtypes:
			return NotImplemented

		new=self.astype(dtype)

		if not self._is_dense:
			self._is_dense = True
			warnings.warn("Mixing dense objects will cast internal matrices to dense.",HamiltonianEfficiencyWarning,stacklevel=3)

		new._static = _np.asarray(new._static.dot(other))

		if _check_almost_zero(new._static):
			new._static = _sp.csr_matrix(new._shape,dtype=new._dtype)

		for func in list(new._dynamic):
			new._dynamic[func] = _np.asarray(new._dynamic[func].dot(other))

			if _check_almost_zero(new._dynamic[func]):
				new._dynamic.pop(func)

		new.check_is_dense()

		return new





	def _rmul_dense(self,other):

		dtype = _np.result_type(self._dtype, other.dtype)

		if dtype not in supported_dtypes:
			return NotImplemented

		new=self.astype(dtype)

		if not self._is_dense:
			self._is_dense = True
			warnings.warn("Mixing dense objects will cast internal matrices to dense.",HamiltonianEfficiencyWarning,stacklevel=3)


		if _sp.issparse(new._static):
			new._static = _np.asarray(other * new._static)
		else:
			new._static = _np.asarray(other.dot(new._static))

		if _check_almost_zero(new._static):
			new._static = _sp.csr_matrix(new._shape,dtype=new._dtype)



		for func in list(new._dynamic):
			if _sp.issparse(new._dynamic[func]):
				new._dynamic[func] = _np.asarray(other * new._dynamic[func])
			else:
				new._dynamic[func] = _np.asarray(other.dot(new._dynamic[func]))
			

			if _check_almost_zero(new._dynamic[func]):
				new._dynamic.pop(func)

		new.check_is_dense()

		return new





	def _imul_dense(self,other):

		if not self._is_dense:
			self._is_dense = True
			warnings.warn("Mixing dense objects will cast internal matrices to dense.",HamiltonianEfficiencyWarning,stacklevel=3)


		self._static = _np.asarray(self._static.dot(other))

		if _check_almost_zero(self._static):
			self._static = _sp.csr_matrix(self._shape,dtype=self._dtype)

		for func in list(self._dynamic):
			self._dynamic[func] = _np.asarray(self._dynamic[func].dot(other))

			if _check_almost_zero(self._dynamic[func]):
				self._dynamic.pop(func)

		self.check_is_dense()

		return _shallowcopy(self)


	
	def __numpy_ufunc__(self, func, method, pos, inputs, **kwargs):
		"""Method for compatibility with NumPy's ufuncs and dot
		functions.
		"""

		if (func == np.dot) or (func == np.multiply):
			if pos == 0:
				return self.__mul__(inputs[1])
			if pos == 1:
				return self.__rmul__(inputs[0])
			else:
				return NotImplemented




def ishamiltonian(obj):
	return isinstance(obj,hamiltonian)



