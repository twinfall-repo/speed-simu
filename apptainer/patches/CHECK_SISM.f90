!    Copyright (C) 2012 The SPEED FOUNDATION
!    Author: Ilario Mazzieri
!
!    This file is part of SPEED.
!
!    SPEED is free software; you can redistribute it and/or modify it
!    under the terms of the GNU Affero General Public License as
!    published by the Free Software Foundation, either version 3 of the
!    License, or (at your option) any later version.
!
!    SPEED is distributed in the hope that it will be useful, but
!    WITHOUT ANY WARRANTY; without even the implied warranty of
!    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
!    Affero General Public License for more details.
!
!    You should have received a copy of the GNU Affero General Public License
!    along with SPEED.  If not, see <http://www.gnu.org/licenses/>.

!> @brief Fills array check_ns for seismic force.
!! @author Ilario Mazzieri
!> @date September, 2013 
!> @version 1.0
!> @param[in] cs_nnz length of cs  
!> @param[in] cs spectral connectivity vector
!> @param[in] nm number of materials
!> @param[in] tm label for materias 
!> @param[in] sd polynomial degree vector
!> @param[in] nl_sism  number of seismic loads
!> @param[in] num_ns  number of seismic nodes
!> @param[in] max_num_ns  max number of seismic nodes
!> @param[in] sour_ns seismic source
!> @param[in] dist_sour_ns  distance of the node from the seismic source
!> @param[in] length_cns  length check seismic nodes (useless)
!> @param[in] fun_sism  function associeted with the seismic load
!> @param[in] nf  number of functions
!> @param[in] tag_func tag for seismic functions
!> @param[in] val_sism values for the seismic loads
!> @param[in] nn_loc number of local nodes
!> @param[in] local_n_num  local numeration vector
!> @param[out] check_ns  check_ns(i,1)  seismic source node, 
!!      check_ns(i,2)  seismic function for the node i,
!!      check_ns(i,3)  i for seismic load,
!!      check_ns(i,4)  number of the element       
!> @param[out]  check_dist_ns check_dist_ns(i,1)  dist_sour_ns / val_sism

      subroutine  CHECK_SISM(cs_nnz,cs,&
                          nm,tm,sd,&
                          nl_sism,&
                          num_ns,max_num_ns,&
                          sour_ns,dist_sour_ns,&
                          pos_sour_nx, pos_sour_ny, pos_sour_nz, &
                          check_ns,check_dist_ns,&
                          length_cns,&
                          check_pos_ns, &
                          fun_sism,nf,tag_func,val_sism,&
                          nn_loc, local_n_num,srcmodflag,szsism)



!      use speed_par, only: slip_type
      
      implicit none
            
      integer*4 :: cs_nnz,nm,ne,nl_sism,nf, nn_loc
      integer*4 :: max_num_ns
      integer*4 :: im,ie,isism,nn
      integer*4 :: is,in,ip
      integer*4 :: i,j,k,h
      integer*4 :: fn
      integer*4 :: length_cns,srcmodflag,szsism,val_st
            
      integer*4, dimension(0:cs_nnz) :: cs
      integer*4, dimension(nm) :: tm,sd
      integer*4, dimension(nl_sism) :: num_ns
      integer*4, dimension(nl_sism) :: fun_sism
      integer*4, dimension(nn_loc) :: local_n_num
      integer*4, dimension(nf) :: tag_func
      
      integer*4, dimension(max_num_ns,nl_sism) :: sour_ns
      integer*4, dimension(length_cns,4) :: check_ns
            
      real*8 :: vel_prop, dist_b, xb, yb, zb, trup_b, dist_p, trup_p, t1_b, tau_b
      real*8 :: dumvr, delay_tr
      
      real*8, dimension(:), allocatable :: ct,ww
      
      real*8, dimension(:,:), allocatable :: dd
      real*8, dimension(max_num_ns,nl_sism) :: dist_sour_ns
      real*8, dimension(max_num_ns,nl_sism) :: pos_sour_nx, pos_sour_ny, pos_sour_nz 
      real*8, dimension(length_cns,1) :: check_dist_ns
      real*8, dimension(length_cns,3) :: check_pos_ns
      real*8, dimension(nl_sism,szsism) :: val_sism
      
      
      
      
      h = 0
      nn = 2
      ne = cs(0) -1

      if (srcmodflag.eq.0) then
        val_st = 12
      elseif (srcmodflag.eq.1 .OR. srcmodflag.eq.2) then
        val_st = 6
      endif
      
      allocate(ct(nn),ww(nn),dd(nn,nn))
      call MAKE_LGL_NW(nn,ct,ww,dd)
   
      do im = 1,nm
         if ((sd(im) +1).ne.nn) then
            deallocate(ct,ww,dd)
            nn = sd(im) +1
            allocate(ct(nn),ww(nn),dd(nn,nn))
            call MAKE_LGL_NW(nn,ct,ww,dd)
         endif
         
         do ie = 1,ne
            if (cs(cs(ie -1) +0).eq.tm(im)) then
                do k = 1,nn
                   do j = 1,nn
                      do i = 1,nn
                         is = nn*nn*(k -1) +nn*(j -1) +i
                         in = cs(cs(ie -1) +is)

                         do isism = 1,nl_sism
                            do ip = 1,num_ns(isism)

                                if (local_n_num(in) .eq. sour_ns(ip,isism)) then
                                     h = h + 1
                                     check_ns(h,1) = sour_ns(ip,isism) !source node
                                     check_ns(h,2) = fun_sism(isism)   !fun type
                                     check_ns(h,3) = isism             !fault number
                                     check_ns(h,4) = ie                !local element
                                     ! new --- added position of nodes 
                                     check_pos_ns(h,1) = pos_sour_nx(ip, isism)
                                     check_pos_ns(h,2) = pos_sour_ny(ip, isism)
                                     check_pos_ns(h,3) = pos_sour_nz(ip, isism)                                                                          
                                     
                                     !!distance from hypo / rupture velocity = rupture time --> std
                                     !!rupture time  ---> Archuleta (line 120 ~ rupt. velocity)
                                     !!write(*,*) slip_type
                                     !!read(*,*)
                                     !!if     (slip_type .eq. 'STD') then 
                                     !   !check_dist_ns(h,1) = dist_sour_ns(ip,isism) / val_sism(isism,19)
                                     !   !old version val_sism(isism,19) = vrup
                                     !   !new_version val_sism(isism,19) = trup
                                     check_dist_ns(h,1) = val_sism(isism,val_st+7)  ! Trupt for the baricenter of the triangle
                                     !!elseif (slip_type .eq. 'ARC') then
                                     !!   check_dist_ns(h,1) = val_sism(isism,19)
                                     !!elseif (slip_type .eq. 'GAL') then
                                     !!   check_dist_ns(h,1) = val_sism(isism,19)
                                     !!endif
                                     !! New implementation for trup (node by node)
                                     !trup_b : dist_b = trup_p : dist_p --> trup_p = (trup_b * dist_p)/dist_b
                                     if (srcmodflag.eq.0) then
                                         xb = (val_sism(isism,4) + val_sism(isism,7) + val_sism(isism,10))/3.d0;
                                         yb = (val_sism(isism,5) + val_sism(isism,8) + val_sism(isism,11))/3.d0;
                                         zb = (val_sism(isism,6) + val_sism(isism,9) + val_sism(isism,12))/3.d0;
                                         
                                         trup_b = val_sism(isism,19)                                   
                                         dist_b = dsqrt((val_sism(isism,1)-xb)**2.d0+(val_sism(isism,2)-yb)**2.d0+(val_sism(isism,3)-zb)**2.d0);
                                         dist_p = dsqrt((val_sism(isism,1)-check_pos_ns(h,1))**2.d0 & 
                                                       +(val_sism(isism,2)-check_pos_ns(h,2))**2.d0 & 
                                                       +(val_sism(isism,3)-check_pos_ns(h,3))**2.d0); 
                                                       
                                         trup_p = trup_b*dist_p/dist_b;              
                                         
                                         !write(*,*) h, dist_b, trup_b, dist_p, trup_p

                                         if (dabs(dist_b) .le. 100) then
                                            check_dist_ns(h,1) =  val_sism(isism,19)
                                         else
                                            check_dist_ns(h,1) = (val_sism(isism,19) * dist_sour_ns(ip,isism)) / dist_b;
                                         endif

                                     elseif (srcmodflag.eq.1 .OR. srcmodflag.eq.2) then
                                          xb = val_sism(isism,4)
                                          yb = val_sism(isism,5)
                                          zb = val_sism(isism,6)
                                          dist_b = dsqrt((val_sism(isism,1)-xb)**2.d0+(val_sism(isism,2)-yb)**2.d0+(val_sism(isism,3)-zb)**2.d0)
                                          dist_p = dsqrt((val_sism(isism,1)-check_pos_ns(h,1))**2.d0 & 
                                                       +(val_sism(isism,2)-check_pos_ns(h,2))**2.d0 & 
                                                       +(val_sism(isism,3)-check_pos_ns(h,3))**2.d0); 

                                          trup_b = val_sism(isism,13) 
                                          tau_b = val_sism(isism,15)
                                          if (szsism .ge. 16) t1_b = val_sism(isism,16)   ! FIX: column 16 exists only with LOAD-SRCMOD3
 
                                          !write(*,*) h, trup_b, tau_b, t1_b

                                          if (dabs(dist_b) .le. 100) then
                                            check_dist_ns(h,1) =  val_sism(isism,val_st+7);
                                         else
                                            ! delay_tr = Rupture time delay for respective segment + time window delay
                                            !dumvr = 2500;
                                            !delay_tr = val_sism(isism,val_st+7) - (dist_b/dumvr);
                                            !check_dist_ns(h,1) = delay_tr + (dist_p/dumvr);
                                            check_dist_ns(h,1) = val_sism(isism,val_st+7)*dist_p/dist_b;
                                         endif
                                     endif
                                     
                                                                          
                                     
                                     
                                 endif

                             enddo  !ip
                         enddo  !isism

                      enddo  !i
                    enddo  !j
                  enddo  !k
             

             endif  !if (cs....)

            enddo  !ie = 1,ne

          enddo !im = 1,nm 

      return

      end subroutine  CHECK_SISM


